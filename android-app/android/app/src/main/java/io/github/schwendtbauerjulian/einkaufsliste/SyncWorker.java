package io.github.schwendtbauerjulian.einkaufsliste;

import android.content.Context;
import android.util.Log;
import androidx.annotation.NonNull;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Überträgt offline gesammelte Änderungen, während die App im Hintergrund oder geschlossen ist.
 *
 * Macht dasselbe wie sync() in app.js: Warteschlange an /api/einkaufsliste/{list}/sync schicken,
 * aktuellen Stand speichern. Android startet den Auftrag, sobald eine Netzverbindung besteht, und
 * wiederholt ihn, solange Home Assistant nicht erreichbar ist (z. B. Adresse nur im Heimnetz).
 * Wie die App probiert er alle Adressen (Heimnetz, Ausweich wie Tailscale), die zuletzt erreichbare zuerst.
 * Doppelt übertragene Änderungen erkennt Home Assistant an ihrer op_id.
 */
public class SyncWorker extends Worker {

    private static final String TAG = "Einkaufsliste";
    private static final String WORK_NAME = "einkaufsliste-sync";
    private static final int CONNECT_TIMEOUT_MS = 5000;
    private static final int READ_TIMEOUT_MS = 15000;

    /** Anmeldung ungültig: Wiederholen hilft nicht, die App fragt beim nächsten Öffnen neu. */
    private static class AuthException extends Exception {}

    private static class Response {

        final int status;
        final String body;

        Response(int status, String body) {
            this.status = status;
            this.body = body;
        }

        boolean ok() {
            return status >= 200 && status < 300;
        }
    }

    public SyncWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    static void schedule(Context context) {
        if (pendingOps(context) == 0) return;
        Constraints constraints = new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(SyncWorker.class)
            .setConstraints(constraints)
            // Linear statt exponentiell: auch nach Stunden ohne Verbindung noch alle paar Minuten versuchen
            .setBackoffCriteria(BackoffPolicy.LINEAR, 1, TimeUnit.MINUTES)
            .build();
        WorkManager.getInstance(context).enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.REPLACE, request);
    }

    static void cancel(Context context) {
        WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME);
    }

    private static int pendingOps(Context context) {
        try {
            String raw = SyncStore.get(context, SyncStore.STATE);
            return raw == null ? 0 : new JSONObject(raw).optJSONArray("queue").length();
        } catch (JSONException | NullPointerException e) {
            return 0;
        }
    }

    @NonNull
    @Override
    public Result doWork() {
        Context context = getApplicationContext();
        try {
            String rawAuth = SyncStore.get(context, SyncStore.AUTH);
            String rawState = SyncStore.get(context, SyncStore.STATE);
            if (rawAuth == null || rawState == null) return Result.success();
            JSONObject auth = new JSONObject(rawAuth);
            JSONObject state = new JSONObject(rawState);
            String listId = state.optString("listId", "");
            JSONArray ops = state.optJSONArray("queue");
            if (listId.isEmpty() || ops == null || ops.length() == 0 || !auth.has("server")) {
                return Result.success();
            }

            String path = "/api/einkaufsliste/" + URLEncoder.encode(listId, "UTF-8") + "/sync";
            String body = new JSONObject().put("ops", ops).toString();
            Response res = post(auth, path, "application/json", body, accessToken(auth, false));
            if (res.status == 401) {
                // Zugangsschlüssel abgelehnt: einmal erneuern und nochmal versuchen
                res = post(auth, path, "application/json", body, accessToken(auth, true));
                if (res.status == 401) throw new AuthException();
            }
            if (res.status == 404) {
                // Liste wurde gelöscht – die App wählt beim nächsten Öffnen eine andere
                state.put("listId", "");
                SyncStore.put(context, SyncStore.STATE, state.toString());
                return Result.success();
            }
            if (res.status == 400) {
                // Fehlerhafte Änderungen verwerfen, sonst blockieren sie alles Weitere
                Log.w(TAG, "Sync abgelehnt: " + res.body);
                store(context, ops, null);
                return Result.success();
            }
            if (!res.ok()) return Result.retry();
            store(context, ops, new JSONObject(res.body));
            Log.i(TAG, ops.length() + " Änderung(en) im Hintergrund übertragen");
            return Result.success();
        } catch (AuthException e) {
            Log.w(TAG, "Anmeldung abgelaufen – Abgleich erst nach erneuter Anmeldung");
            return Result.success();
        } catch (IOException e) {
            Log.i(TAG, "Home Assistant nicht erreichbar, neuer Versuch später: " + e.getMessage());
            return Result.retry();
        } catch (JSONException e) {
            Log.w(TAG, "Ungültige Daten", e);
            return Result.failure();
        }
    }

    /** Übertragene Änderungen aus der Warteschlange nehmen und den neuen Stand übernehmen. */
    private static void store(Context context, JSONArray sent, JSONObject data) throws JSONException {
        synchronized (SyncStore.class) {
            JSONObject state = new JSONObject(SyncStore.get(context, SyncStore.STATE));
            Set<String> sentIds = new HashSet<>();
            for (int i = 0; i < sent.length(); i++) {
                sentIds.add(sent.getJSONObject(i).optString("op_id"));
            }
            JSONArray queue = state.optJSONArray("queue");
            JSONArray rest = new JSONArray();
            for (int i = 0; queue != null && i < queue.length(); i++) {
                JSONObject op = queue.getJSONObject(i);
                if (!sentIds.contains(op.optString("op_id"))) rest.put(op);
            }
            state.put("queue", rest);
            if (data != null) {
                JSONObject base = new JSONObject();
                base.put("items", data.optJSONArray("items") != null ? data.getJSONArray("items") : new JSONArray());
                base.put("history", data.optJSONArray("history") != null ? data.getJSONArray("history") : new JSONArray());
                state.put("base", base);
                state.put("lastSync", System.currentTimeMillis());
            }
            SyncStore.put(context, SyncStore.STATE, state.toString());
        }
    }

    /** Gültiger Zugangsschlüssel; wird bei Bedarf mit dem Refresh-Token erneuert (wie in app.js). */
    private String accessToken(JSONObject auth, boolean force) throws IOException, JSONException, AuthException {
        if (!force && System.currentTimeMillis() < auth.optLong("expires", 0) - 60000) {
            return auth.getString("access_token");
        }
        String form =
            "grant_type=refresh_token" +
            "&refresh_token=" + URLEncoder.encode(auth.getString("refresh_token"), "UTF-8") +
            "&client_id=" + URLEncoder.encode(auth.getString("client_id"), "UTF-8");
        Response res = post(auth, "/auth/token", "application/x-www-form-urlencoded", form, null);
        if (res.status == 400 || res.status == 401 || res.status == 403) throw new AuthException();
        if (!res.ok()) throw new IOException("HTTP " + res.status);
        JSONObject data = new JSONObject(res.body);
        auth.put("access_token", data.getString("access_token"));
        auth.put("expires", System.currentTimeMillis() + data.getLong("expires_in") * 1000);
        if (data.has("refresh_token")) auth.put("refresh_token", data.getString("refresh_token"));
        SyncStore.put(getApplicationContext(), SyncStore.AUTH, auth.toString());
        return auth.getString("access_token");
    }

    /** Adressen von Home Assistant, die zuletzt erreichbare zuerst (wie serverList() in app.js). */
    private static List<String> servers(JSONObject auth) {
        Set<String> result = new LinkedHashSet<>();
        String last = auth.optString("server", "");
        if (!last.isEmpty()) result.add(last);
        JSONArray all = auth.optJSONArray("servers");
        for (int i = 0; all != null && i < all.length(); i++) {
            String server = all.optString(i, "");
            if (!server.isEmpty()) result.add(server);
        }
        return new ArrayList<>(result);
    }

    /** Alle Adressen der Reihe nach probieren; die erreichbare wird für das nächste Mal gemerkt. */
    private Response post(JSONObject auth, String path, String contentType, String body, String token)
        throws IOException, JSONException {
        IOException error = new IOException("Keine Adresse");
        for (String server : servers(auth)) {
            try {
                Response res = post(server + path, contentType, body, token);
                if (!server.equals(auth.optString("server"))) {
                    Log.i(TAG, "Home Assistant erreichbar über " + server);
                    auth.put("server", server);
                    SyncStore.put(getApplicationContext(), SyncStore.AUTH, auth.toString());
                }
                return res;
            } catch (IOException e) {
                error = e;
            }
        }
        throw error;
    }

    private static Response post(String url, String contentType, String body, String token) throws IOException {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        try {
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
            conn.setReadTimeout(READ_TIMEOUT_MS);
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", contentType);
            if (token != null) conn.setRequestProperty("Authorization", "Bearer " + token);
            try (OutputStream out = conn.getOutputStream()) {
                out.write(body.getBytes(StandardCharsets.UTF_8));
            }
            int status = conn.getResponseCode();
            InputStream in = status >= 400 ? conn.getErrorStream() : conn.getInputStream();
            return new Response(status, in == null ? "" : readAll(in));
        } finally {
            conn.disconnect();
        }
    }

    private static String readAll(InputStream in) throws IOException {
        try (InputStream stream = in) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int n;
            while ((n = stream.read(buffer)) != -1) out.write(buffer, 0, n);
            return out.toString("UTF-8");
        }
    }
}
