#!/usr/bin/with-contenv bashio
# Installiert bzw. aktualisiert die Integration und startet die Oberfläche für die Seitenleiste.

SRC=/integration/einkaufsliste
DEST=/homeassistant/custom_components/einkaufsliste

checksum() {
    (cd "$1" && find . -type f ! -path "*/__pycache__/*" | sort | xargs sha256sum) | sha256sum | cut -d" " -f1
}

core_service() {
    curl -sS -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$2" \
        "http://supervisor/core/api/services/$1" > /dev/null \
        || bashio::log.warning "Aufruf von $1 fehlgeschlagen"
}

if [ -d "$DEST" ] && [ "$(checksum "$SRC")" = "$(checksum "$DEST")" ]; then
    bashio::log.info "Integration ist aktuell."
else
    FIRST_INSTALL=true
    [ -d "$DEST" ] && FIRST_INSTALL=false

    bashio::log.info "Installiere Integration nach ${DEST} ..."
    mkdir -p /homeassistant/custom_components
    rm -rf "$DEST"
    cp -r "$SRC" "$DEST"

    if bashio::config.true 'auto_restart'; then
        bashio::log.info "Starte Home Assistant neu ..."
        core_service "homeassistant/restart" "{}"
    elif [ "$FIRST_INSTALL" = true ]; then
        core_service "persistent_notification/create" '{
            "notification_id": "einkaufsliste_installiert",
            "title": "Einkaufsliste installiert",
            "message": "Bitte Home Assistant einmal neu starten (Einstellungen → System → Neu starten). Danach unter Einstellungen → Geräte & Dienste → Integration hinzufügen → „Einkaufsliste“ einrichten."
        }'
    else
        core_service "persistent_notification/create" '{
            "notification_id": "einkaufsliste_aktualisiert",
            "title": "Einkaufsliste aktualisiert",
            "message": "Bitte Home Assistant neu starten, damit die neue Version aktiv wird."
        }'
    fi
fi

bashio::log.info "Starte Oberfläche für die Seitenleiste ..."
exec python3 /server.py
