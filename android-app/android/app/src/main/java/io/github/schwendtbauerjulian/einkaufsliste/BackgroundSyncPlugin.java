package io.github.schwendtbauerjulian.einkaufsliste;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Brücke zur Web-App: Sie legt Zustand und Anmeldung hier ab. Geht die App in den Hintergrund,
 * wird der Abgleich geplant; kommt sie zurück, übernimmt wieder die Web-App.
 */
@CapacitorPlugin(name = "BackgroundSync")
public class BackgroundSyncPlugin extends Plugin {

    @PluginMethod
    public void save(PluginCall call) {
        String key = call.getString("key");
        if (!SyncStore.STATE.equals(key) && !SyncStore.AUTH.equals(key)) {
            call.reject("Unbekannter Schlüssel: " + key);
            return;
        }
        SyncStore.put(getContext(), key, call.getString("value"));
        call.resolve();
    }

    @PluginMethod
    public void load(PluginCall call) {
        JSObject result = new JSObject();
        result.put(SyncStore.STATE, SyncStore.get(getContext(), SyncStore.STATE));
        result.put(SyncStore.AUTH, SyncStore.get(getContext(), SyncStore.AUTH));
        call.resolve(result);
    }

    @Override
    protected void handleOnPause() {
        SyncWorker.schedule(getContext());
    }

    @Override
    protected void handleOnResume() {
        SyncWorker.cancel(getContext());
    }
}
