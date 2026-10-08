package io.github.schwendtbauerjulian.einkaufsliste;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Gemeinsamer Speicher von Web-App und Hintergrund-Abgleich.
 *
 * "state" = Zustand der Web-App (Liste, Warteschlange), "auth" = Anmeldung; beides als JSON-Text,
 * genau so wie die Web-App es im localStorage ablegt.
 */
final class SyncStore {

    static final String STATE = "state";
    static final String AUTH = "auth";
    private static final String PREFS = "einkaufsliste-sync";

    private SyncStore() {}

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static synchronized String get(Context context, String key) {
        return prefs(context).getString(key, null);
    }

    static synchronized void put(Context context, String key, String value) {
        SharedPreferences.Editor editor = prefs(context).edit();
        if (value == null) {
            editor.remove(key);
        } else {
            editor.putString(key, value);
        }
        editor.commit();
    }
}
