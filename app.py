import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
import pytz
from datetime import datetime

# ==============================================================================
# ABSCHNITT 0: KONFIGURATION & GLOBALE VARIABLEN
# ==============================================================================

# Google Sheets Konfiguration (Annahme: Secrets sind jetzt korrekt gesetzt)
SHEET_ID = st.secrets.sheet_id      
WORKSHEET_NAME = "Laufdaten"      # Sheet, das die eigentlichen Laufdaten enthält

# Zeitzonen- und Zeitstempel-Konfiguration
TIMEZONE = pytz.timezone('Europe/Berlin')
LAST_LOAD_TIME = datetime.now(TIMEZONE).strftime("%d.%m.%Y, %H:%M Uhr")

# Challenge-Ziel
ZIEL_KM = 3500 

# Konfiguration des Streamlit-Seitenlayouts
st.set_page_config(
    page_title="SSV Laufchallenge Dashboard",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialisierung des gspread-Clients
try:
    gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
except Exception as e:
    st.error(f"Fehler beim Initialisieren des Google Sheets Clients: {e}")
    st.stop()


# ==============================================================================
# ABSCHNITT 1: DATEN LADEN & VORBEREITEN (NEU: Merge von Teilnehmer und Laufdaten)
# ==============================================================================

@st.cache_data(ttl=86400)
def load_data():
    """
    Lädt Teilnehmerliste und Laufdaten, führt sie zusammen (Left-Join) und bereitet sie vor.
    Stellt sicher, dass 0-KM-Läufer enthalten sind.
    """
    
    # ----------------------------------------------------------------------
    # 1. TEILNEHMERLISTE LADEN ('Teilnehmer' Sheet)
    try:
        wks_teilnehmer = gc.open_by_key(SHEET_ID).worksheet("Teilnehmer")
        df_teilnehmer = pd.DataFrame(wks_teilnehmer.get_all_records())
        
        if 'Name' not in df_teilnehmer.columns or 'Gruppe' not in df_teilnehmer.columns:
            st.error("Fehler: Das 'Teilnehmer'-Sheet muss die Spalten 'Name' und 'Gruppe' enthalten.")
            return pd.DataFrame() 
            
    except Exception as e:
        st.error(f"Fehler beim Laden der Teilnehmerliste (Sheet 'Teilnehmer'): {e}")
        return pd.DataFrame()

    # ----------------------------------------------------------------------
    # 2. LAUFDATEN LADEN ('Laufdaten' Sheet)
    try:
        wks_laufdaten = gc.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME) 
        df_laufdaten = pd.DataFrame(wks_laufdaten.get_all_records())
        
    except Exception as e:
        st.warning(f"Warnung: Fehler beim Laden der Laufdaten (Sheet '{WORKSHEET_NAME}'). Führe mit leeren Laufdaten fort: {e}")
        df_laufdaten = pd.DataFrame({'Name': [], 'KM': []})

    # ----------------------------------------------------------------------
    # 3. DATEN VORBEREITEN UND ZUSAMMENFÜHREN
    
    # Laufdaten: KM in numerisches Format bringen, Fehler als 0 behandeln
    df_laufdaten['KM'] = pd.to_numeric(df_laufdaten.get('KM', 0), errors='coerce').fillna(0)
    
    # Summe der KM pro Teilnehmer berechnen (nur Name und KM sind hier wichtig)
    df_summe_km = df_laufdaten.groupby('Name', as_index=False)['KM'].sum()

    # Zusammenführen mit der vollständigen Teilnehmerliste (Left-Join)
    # Behält alle Teilnehmer aus der Liste bei und fügt die Gesamt-KM hinzu.
    df = pd.merge(df_teilnehmer, df_summe_km, on='Name', how='left')

    # KM-Spalte für Läufer, die noch keine Daten haben, auf 0 setzen
    df['KM'] = df['KM'].fillna(0)
    
    return df

# Daten laden
df_raw = load_data()


# ==============================================================================
# ABSCHNITT 2: DATENAGGREGATIONEN & PRÜFUNG
# ==============================================================================

if df_raw.empty:
    # st.error wird bereits in load_data() aufgerufen, aber zur Sicherheit
    st.error("Dashboard konnte keine Daten laden. Bitte prüfen Sie Secrets und Sheet-Namen.")
    st.stop()


# Berechne Gesamt-KM und den Fortschritt
gesamt_km = df_raw['KM'].sum()
fortschritt = min(gesamt_km / ZIEL_KM, 1.0) 

# Berechne die aggregierten Daten für die Charts
df_gruppen = df_raw.groupby('Gruppe')['KM'].sum().reset_index()
df_gruppen.columns = ['Gruppe', 'Gesamt-KM']
df_gruppen = df_gruppen.sort_values(by='Gesamt-KM', ascending=False)


# ==============================================================================
# ABSCHNITT 3: DASHBOARD-LAYOUT (WIE VORHER)
# ==============================================================================

st.title("🏃 SSV Laufchallenge Dashboard")
st.caption(f"Letzte Aktualisierung der Daten: {LAST_LOAD_TIME}")

# ----------------------------------------------------------------------
# ROW 1: Fortschritt und Kennzahlen
# ----------------------------------------------------------------------

st.header("Challenge-Übersicht")

col_prog, col_km, col_teilnehmer = st.columns(3)

with col_km:
    st.metric(label="Gesamtkilometer", value=f"{gesamt_km:,.1f} KM", delta=f"{ZIEL_KM - gesamt_km:,.1f} KM zum Ziel")

with col_teilnehmer:
    aktive_teilnehmer = df_raw[df_raw['KM'] > 0]['Name'].nunique()
    alle_teilnehmer = df_raw['Name'].nunique()
    st.metric(label="Aktive Teilnehmer", value=f"{aktive_teilnehmer} / {alle_teilnehmer}", delta=f"{alle_teilnehmer - aktive_teilnehmer} Personen warten noch")

with col_prog:
    st.metric(label="Ziel-KM", value=f"{ZIEL_KM:,} KM")
    st.progress(fortschritt, text=f"**{fortschritt*100:.1f}%** des Ziels erreicht ({gesamt_km:,.1f} von {ZIEL_KM:,} KM)")


# ----------------------------------------------------------------------
# SIDEBAR: Filter für Einzel-Ansicht
# ----------------------------------------------------------------------

st.sidebar.header("Filter & Ansicht")

# Filter 1: Gruppe
alle_gruppen = ['Alle'] + sorted(df_raw['Gruppe'].unique())
selected_gruppe = st.sidebar.selectbox("Nach Gruppe filtern", alle_gruppen)

# Filter 2: Top-Läufer
top_n = st.sidebar.slider("Top N Läufer anzeigen", min_value=5, max_value=df_raw['Name'].nunique(), value=20)

# Filter 3: 0 KM Läufer ausblenden
hide_zero = st.sidebar.checkbox("Läufer ohne KM ausblenden", value=False)


# ----------------------------------------------------------------------
# ROW 2: Diagramme (Tabs)
# ----------------------------------------------------------------------

st.markdown("---")
st.header("Analysen")

tab_gruppen, tab_einzel = st.tabs(["🏆 Gruppen-Rangliste", "🧑 Einzel-Rangliste"])

# --- TAB: GRUPPEN-RANGLISTE ---
with tab_gruppen:
    st.subheader("Kumulierte Laufleistung pro Gruppe")
    
    # Sortierung für das Ranking (höchste KM zuerst)
    df_gruppen_rank = df_gruppen.sort_values(by='Gesamt-KM', ascending=True)

    fig_gruppen = px.bar(
        df_gruppen_rank,
        y='Gruppe',
        x='Gesamt-KM',
        orientation='h',
        color='Gruppe',
        text='Gesamt-KM',
        labels={'Gesamt-KM': 'Gesamtkilometer', 'Gruppe': 'Gruppe'},
        height=400,
        title='Gruppenleistung (Gesamt-KM)'
    )
    
    fig_gruppen.update_traces(texttemplate='%{text:.1f} KM', textposition='outside')
    fig_gruppen.update_layout(xaxis_title='Gesamtkilometer', yaxis_title='')
    
    st.plotly_chart(fig_gruppen, use_container_width=True)

# --- TAB: EINZEL-RANGLISTE ---
with tab_einzel:
    st.subheader("Laufleistung pro Teilnehmer")
    
    # ----------------------------------------------------------------------
    # Filter-Anwendung
    # ----------------------------------------------------------------------
    
    df_final = df_raw.copy()

    # Gruppe filtern
    if selected_gruppe != 'Alle':
        df_final = df_final[df_final['Gruppe'] == selected_gruppe]

    # 0 KM ausblenden
    if hide_zero:
        df_final = df_final[df_final['KM'] > 0]
        
    # Sortieren nach KM
    df_final = df_final.sort_values(by='KM', ascending=False)
    
    # Top N anwenden
    if df_final.shape[0] > top_n:
        df_final = df_final.head(top_n)

    
    # ----------------------------------------------------------------------
    # Chart-Erstellung
    # ----------------------------------------------------------------------
    
    if df_final.empty:
        st.info("Keine Daten nach Anwendung der Filter gefunden.")
    else:
        # Sortierung für Plotly (höchste KM zuerst im Chart)
        df_plot = df_final.sort_values(by='KM', ascending=True)
        
        fig_einzel = px.bar(
            df_plot,
            y='Name',
            x='KM',
            orientation='h',
            color='Gruppe',
            text='KM',
            labels={'KM': 'Gesamtkilometer', 'Name': 'Teilnehmer'},
            height=600,
            title=f'Top {df_plot.shape[0]} Einzel-Läufer (Gesamt-KM)'
        )
        
        fig_einzel.update_traces(texttemplate='%{text:.1f} KM', textposition='outside')
        fig_einzel.update_layout(xaxis_title='Gesamtkilometer', yaxis_title='')
        
        st.plotly_chart(fig_einzel, use_container_width=True)

# ----------------------------------------------------------------------
# ROW 3: Rohtabelle
# ----------------------------------------------------------------------

st.markdown("---")
st.subheader("Detailübersicht (sortierbar)")

# Sortierung für die Tabelle (höchste KM zuerst)
df_display = df_raw.sort_values(by='KM', ascending=False).reset_index(drop=True)
df_display.index = df_display.index + 1 # Index beginnt bei 1

st.dataframe(df_display, use_container_width=True)

# Ende des Codes
