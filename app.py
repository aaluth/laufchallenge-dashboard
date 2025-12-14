import streamlit as st
import pandas as pd
import gspread 
import plotly.express as px
import plotly.graph_objects as go 
from datetime import datetime 
import pytz # Hinzugefügt für Zeitzonen-Korrektur

# ==============================================================================
# 0. KONFIGURATION & GLOBALE VARIABLEN
# ==============================================================================

# Branding-Farben des Suchsdorfer SV
PRIMARY_COLOR = "#002060"  
TEXT_COLOR = "#212121"    
BACKGROUND_COLOR = "#FFFFFF" 
SECONDARY_BACKGROUND_COLOR = "#F0F2F6" 

# Challenge Zeitraum KWs
CHALLENGE_KWS = [51, 52, 1, 2, 3, 4, 5, 6, 7]
CHALLENGE_KWS_STR = [str(kw) for kw in CHALLENGE_KWS]

st.set_page_config(
    page_title="Laufchallenge Dashboard | Suchsdorfer SV",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Google Sheets Konfiguration (WICHTIG: MUSS MIT DEM SECRET KEY NAMEN ÜBEREINSTIMMEN!)
# Annahme, dass Sie den Secret Key 'sheet_id' in Ihrer Streamlit Cloud konfiguriert haben:
try:
    SHEET_ID = st.secrets.sheet_id
except AttributeError:
    st.error("FEHLER: Konfigurationsschlüssel 'sheet_id' fehlt in Streamlit Secrets.")
    st.stop()
    
WORKSHEET_NAME = "Laufdaten"  # Sheet für die eingetragenen Läufe

# Zeitzonen- und Zeitstempel-Konfiguration (mit pytz korrigiert)
TIMEZONE = pytz.timezone('Europe/Berlin')
LAST_LOAD_TIME = datetime.now(TIMEZONE).strftime("%d.%m.%Y, %H:%M Uhr")

# Initialisierung des gspread-Clients (neu und modernisiert)
try:
    gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
except Exception as e:
    st.error(f"Fehler beim Initialisieren des Google Sheets Clients: {e}")
    st.stop()


# ==============================================================================
# 1. DATEN LADEN (Caching & gspread) - NEUE LOGIK FÜR 2 SHEETS (Teilnehmer & Laufdaten)
# ==============================================================================

@st.cache_data(ttl=86400)
def load_data():
    """
    Lädt die Teilnehmerliste und die Laufdaten, führt sie zusammen (Left-Join).
    Stellt sicher, dass alle 0-KM-Läufer enthalten sind.
    """
    
    # ----------------------------------------------------------------------
    # 1. TEILNEHMERLISTE LADEN ('Teilnehmer' Sheet)
    try:
        wks_teilnehmer = gc.open_by_key(SHEET_ID).worksheet("Teilnehmer")
        df_teilnehmer = pd.DataFrame(wks_teilnehmer.get_all_records())
        
        # Prüfung auf notwendige Spalten
        if 'Name' not in df_teilnehmer.columns or 'Gruppe' not in df_teilnehmer.columns:
            st.error("Fehler: Das 'Teilnehmer'-Sheet muss die Spalten 'Name' und 'Gruppe' enthalten.")
            return pd.DataFrame() 
            
    except Exception as e:
        st.error(f"Fehler beim Laden der Teilnehmerliste (Sheet 'Teilnehmer'). Bitte prüfen Sie den Sheet-Namen und die Zugriffsrechte: {e}")
        return pd.DataFrame()

    # ----------------------------------------------------------------------
    # 2. LAUFDATEN LADEN ('Laufdaten' Sheet)
    try:
        wks_laufdaten = gc.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME) 
        df_laufdaten = pd.DataFrame(wks_laufdaten.get_all_records())
        
    except Exception as e:
        # Warnung, aber kein Stopp, da wir die App mit 0-KM-Läufern weiterführen wollen
        st.warning(f"Warnung: Fehler beim Laden der Laufdaten (Sheet '{WORKSHEET_NAME}'). Führe mit leeren Laufdaten fort: {e}")
        df_laufdaten = pd.DataFrame({'Name': [], 'KM': []})

    # ----------------------------------------------------------------------
    # 3. DATEN VORBEREITEN UND ZUSAMMENFÜHREN
    
    # Laufdaten: KM in numerisches Format bringen, Fehler als 0 behandeln
    df_laufdaten['KM'] = pd.to_numeric(df_laufdaten.get('KM', 0), errors='coerce').fillna(0)
    
    # Aggregation der Laufdaten
    df_summe_km = df_laufdaten.groupby('Name', as_index=False)['KM'].sum()

    # Zusammenführen mit der vollständigen Teilnehmerliste (Left-Join)
    df_merged = pd.merge(df_teilnehmer, df_summe_km, on='Name', how='left')

    # KM-Spalte für Läufer, die noch keine Daten haben, auf 0 setzen
    df_merged['KM'] = df_merged['KM'].fillna(0)
    
    # --- Füge die restlichen Spalten des originalen Dashboards hinzu ---
    # Da wir nun nur die Gesamt-KM pro Name haben, müssen wir die KW/Datum-Infos
    # anders behandeln, wenn wir sie für die Detailansicht brauchen.
    
    # FÜGE ALLE ORIGINAL-DATEN VON df_laufdaten ZURÜCK HINZU (für KW-Chart, falls Name gefiltert wird)
    # Nur Spalten behalten, die nicht 'KM' oder 'Name' sind
    df_others = df_laufdaten.drop(columns=['KM'], errors='ignore')
    
    # Finaler DataFrame (Muss die ursprünglichen Spalten KW und Datum für die Charts enthalten!)
    # Für die Gesamtübersichten reicht df_merged. Für die KW-Entwicklung benötigen wir das Datum/KW.
    
    # Beste Lösung: Der Left-Join ist nur für die 0-KM-Läufer. Wir behalten die Laufdaten
    # im Originalformat, ergänzt um die KW/Datum Transformation, und fügen die 0-KM-Läufer
    # als separate Zeilen mit 0 KM hinzu.
    
    # NEUER ANSATZ: Rückgabe von df_teilnehmer und df_laufdaten.
    return df_teilnehmer, df_laufdaten 

# Ende der load_data Funktion


# ==============================================================================
# 2. DATEN VORBEREITEN & BEREINIGEN (Erweiterte Transformation)
# ==============================================================================

@st.cache_data
def transform_data(df_teilnehmer, df_laufdaten):
    """Konvertiert Datentypen, berechnet Aggregationen und führt die Daten zusammen."""
    
    # 1. Laufdaten bereinigen
    df_laufdaten.columns = [col.strip() for col in df_laufdaten.columns]
    
    if 'KM' not in df_laufdaten.columns:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
    df_laufdaten['KM'] = pd.to_numeric(df_laufdaten['KM'], errors='coerce').fillna(0)
    df_laufdaten['Datum'] = pd.to_datetime(df_laufdaten['Datum'], format='%d.%m.%Y', errors='coerce')
    
    # Wir brauchen pytz, um die KW korrekt zu bestimmen, falls Datum existiert
    try:
        # Annahme: Kalenderwoche wurde im Sheet eingetragen
        df_laufdaten['KW'] = pd.to_numeric(df_laufdaten['KW'], errors='coerce', downcast='integer')
        df_laufdaten['KW_STR'] = df_laufdaten['KW'].astype(str)
    except KeyError:
        # Fallback: KW aus Datum berechnen (wenn Datum im Sheet korrekt ist)
        df_laufdaten['KW'] = df_laufdaten['Datum'].dt.isocalendar().week.astype('Int64')
        df_laufdaten['KW_STR'] = df_laufdaten['KW'].astype(str)
        
    # Filtern nach Challenge-KW (optional, wenn Sie nur die KWs der Challenge sehen wollen)
    df_laufdaten = df_laufdaten[df_laufdaten['KW_STR'].isin(CHALLENGE_KWS_STR)].copy()


    # 2. Zusammenführen der Teilnehmer (für 0-KM-Läufer)
    df_summe_km = df_laufdaten.groupby('Name', as_index=False)['KM'].sum()
    df_merged_gesamt = pd.merge(df_teilnehmer, df_summe_km, on='Name', how='left')
    df_merged_gesamt['KM'] = df_merged_gesamt['KM'].fillna(0)
    
    # ----------------------------------------------------------------------
    # 3. Aggregation für KW-Diagramm (Gesamt)
    # ----------------------------------------------------------------------
    weekly_summary = df_laufdaten.groupby('KW_STR')['KM'].sum().reset_index()
    weekly_summary.rename(columns={'KM': 'Wochen-KM'}, inplace=True)
    
    # ----------------------------------------------------------------------
    # 4. Aggregation und KUMULIERUNG für Gruppen-Diagramm (STATISCHE DATEN)
    # ----------------------------------------------------------------------
    group_weekly = pd.DataFrame() # Initialisiere als leer
    if 'Gruppe' in df_laufdaten.columns:
        
        # KORREKTUR: Setze die KW_STR Spalte als geordnete Kategorie
        df_laufdaten['KW_STR'] = pd.Categorical(
            df_laufdaten['KW_STR'], 
            categories=CHALLENGE_KWS_STR,
            ordered=True
        )

        # 1. Wöchentliche KM pro Gruppe
        group_weekly = df_laufdaten.groupby(['Gruppe', 'KW_STR'], observed=True)['KM'].sum().reset_index()
        
        # 2. Sortiere nach Gruppe und dann nach der korrekten kategorialen KW_STR
        group_weekly = group_weekly.sort_values(['Gruppe', 'KW_STR'])
        
        # 3. Kumuliere die KM pro Gruppe
        group_weekly['Kumulierte_KM'] = group_weekly.groupby('Gruppe')['KM'].cumsum()
    

    # FERTIGE DATENSTRUKTUR FÜR DAS DASHBOARD:
    # df: Der ursprüngliche Datensatz mit allen Läufen (inkl. KW/Datum)
    # df_merged_gesamt: Die aggregierte Liste aller Teilnehmer (inkl. 0-KM-Läufer)

    # Wir müssen die Laufdaten um die Gruppe ergänzen, damit der Filter funktioniert
    df_runs = pd.merge(df_laufdaten, df_teilnehmer[['Name', 'Gruppe']], on='Name', how='left')
    
    # ERGÄNZEN: Füge die 0-KM-Läufer als separate Zeilen hinzu (wichtig für die Filterung in der Sidebar!)
    zero_km_runners = df_merged_gesamt[df_merged_gesamt['KM'] == 0]
    
    # Die 0-KM-Läufer brauchen leere Felder für Datum/KW, aber ihre Name/Gruppe
    zero_km_runners = zero_km_runners[['Name', 'Gruppe', 'KM']].rename(columns={'KM': 'KM_Total'})
    zero_km_runners['KW'] = pd.NA
    
    #df_final = pd.concat([df_runs, zero_km_runners], ignore_index=True)

    return df_runs, weekly_summary, group_weekly, df_merged_gesamt

# Daten laden und transformieren
df_teilnehmer_raw, df_laufdaten_raw = load_data()
df, weekly_summary, group_weekly, df_merged_gesamt = transform_data(df_teilnehmer_raw, df_laufdaten_raw)

# Sicherheits-Check (mit Korrektur für 0-KM-Läufer)
if df_merged_gesamt.empty:
    st.info("Keine gültigen Laufdaten zur Visualisierung gefunden (Fehler beim Merge).")
    st.stop()
# --- Wichtig: Der Stopp-Befehl ist entfernt, da wir alle 0-KM-Läufer anzeigen ---

# ==============================================================================
# 3. DASHBOARD VISUALISIERUNG & FILTER
# ==============================================================================

# --- Sidebar (Logo und Filter) ---
with st.sidebar:
    # Logo wird jetzt lokal geladen
    try:
        # Annahme: 'logo.png' liegt im GitHub-Repo
        st.image("logo.png", width=180)
    except FileNotFoundError:
        st.warning("Logo 'logo.png' nicht gefunden. Bitte speichern Sie die Logodatei im GitHub-Repo.")

    st.markdown(f"<h1 style='text-align: center; color: {PRIMARY_COLOR}; font-size: 2.2em;'>Laufchallenge</h1>", unsafe_allow_html=True)
    st.markdown("---")
    st.subheader("Filter")

    # Verwende df_merged_gesamt für die Filterung (da dort alle Namen/Gruppen enthalten sind)
    df_filtered_km = df_merged_gesamt.copy() 

    # 1. Gruppen-Filter 
    selected_group = 'Alle'
    if 'Gruppe' in df_filtered_km.columns:
        groups = df_filtered_km['Gruppe'].unique()
        selected_group = st.selectbox("1. Wähle Gruppe", ['Alle'] + sorted(list(groups)))

        if selected_group != 'Alle':
            df_filtered_km = df_filtered_km[df_filtered_km['Gruppe'] == selected_group].copy() 

    # 2. Personen-Filter (basierend auf der gefilterten Gruppe)
    selected_runner = 'Alle'
    if 'Name' in df_filtered_km.columns: 
        runners = df_filtered_km['Name'].unique()
        selected_runner = st.selectbox("2. Wähle Name", ['Alle'] + sorted(list(runners))) 

        if selected_runner != 'Alle':
            df_filtered_km = df_filtered_km[df_filtered_km['Name'] == selected_runner].copy()
        
    # 3. KW-Filter (Dieser Filter betrifft nur die Detailtabelle/Bestenlisten im Hauptteil,
    # da die KW-Diagramme die KW-Spalte aus df benötigen, nicht aus df_filtered_km)
    selected_kw = 'Gesamt'
    kw_options = ['Gesamt'] + CHALLENGE_KWS
        
    selected_kw = st.selectbox(
        "3. Wähle Kalenderwoche (KW) für Bestenlisten",
        options=kw_options,
        index=0
    )

# Wichtig: Der Filter für die Detailtabelle/Bestenlisten muss nun auf dem ursprünglichen df (Laufdaten) laufen.
# Wir müssen die Filterung in den entsprechenden Abschnitten (8, 9, 11) neu definieren.


# ==============================================================================
# 4. HAUPTBEREICH DES DASHBOARDS
# ==============================================================================

st.markdown(
    f"""<h1 style='color: {PRIMARY_COLOR};'>Laufchallenge Übersicht</h1>""", 
    unsafe_allow_html=True
)
st.caption(f"Letzte Aktualisierung der Daten: **{LAST_LOAD_TIME}**") 

# --- 4. Metriken (Fortschritt) ---
with st.container(border=True):
    st.markdown(f"<h4 style='color: {PRIMARY_COLOR};'>🚀 Aktueller Fortschritt (Gesamt)</h4>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    
    # Verwenden Sie df_merged_gesamt für die Gesamt-KM, da dort alle 0-KM-Läufer aggregiert sind
    gesamt_km_total = df_merged_gesamt['KM'].sum()
    anzahl_läufe_total = df.shape[0] # Anzahl Läufe basiert auf dem reinen Laufdaten-Sheet

    col1.metric(
        label="Gesamt-KM", 
        value=f"{gesamt_km_total:,.1f} km",
        help="Gesamte Laufstrecke aller Teilnehmer seit Beginn der Challenge."
    ) 
    col2.metric(
        label="Anzahl Läufe", 
        value=f"{anzahl_läufe_total}",
        help="Gesamtzahl aller gemeldeten Laufeinheiten."
    )
    if 'Gruppe' in df_merged_gesamt.columns:
        col3.metric(
            label="Anzahl Gruppen", 
            value=df_merged_gesamt['Gruppe'].nunique(),
            help="Anzahl der Teams, die an der Challenge teilnehmen."
        )

st.markdown("<br>", unsafe_allow_html=True) 

# ==============================================================================
# 5. REKORDE & BESTLEISTUNGEN (STATISCH)
# ==============================================================================

# WICHTIG: Rekorde basieren nur auf df (den tatsächlichen Läufen), da 0-KM-Einträge hier keinen Sinn machen
if 'Name' in df.columns and not df.empty:
    with st.container(border=True):
        st.markdown(f"<h4 style='color: {PRIMARY_COLOR};'>👑 Rekorde & Bestleistungen</h4>", unsafe_allow_html=True)
        record_col1, record_col2 = st.columns(2)

        # --- 1. Längste Einheit ---
        max_km_entry = df.loc[df['KM'].idxmax()]
        max_km = max_km_entry['KM']
        max_km_runner = max_km_entry['Name']
        
        # Sicherstellen, dass Datum als String ausgegeben wird (falls NaN)
        max_km_date = max_km_entry['Datum'].strftime('%d.%m.') if pd.notna(max_km_entry['Datum']) else "Datum unbekannt"
        
        with record_col1:
            st.metric(
                label="🥇 Längste Einzeldistanz",
                value=f"{max_km:,.1f} km",
                help="Die höchste Kilometerzahl, die ein Läufer in einem einzigen Eintrag gemeldet hat."
            )
            st.caption(f"**Rekordhalter:** {max_km_runner} ({max_km_date})")

        # --- 2. Fleißigster Läufer (Runs) ---
        runner_runs = df.groupby('Name')['KM'].count()
        most_runs = runner_runs.max()
        
        runners_with_max_runs = runner_runs[runner_runs == most_runs].index.tolist()
        runners_list = ', '.join(runners_with_max_runs)

        with record_col2:
            st.metric(
                label="🏃 Fleißigster Läufer (Anzahl Läufe)",
                value=f"{most_runs} Läufe",
                help="Der Läufer mit der höchsten Gesamtzahl an gemeldeten Einheiten."
            )
            st.caption(f"**Rekordhalter:** {runners_list}")

st.markdown("<br>", unsafe_allow_html=True) 
st.markdown("---") 

# ==============================================================================
# 6. DIAGRAMM: Gruppen-KM-Vergleich 
# ==============================================================================

ranking_period = selected_kw if selected_kw != 'Gesamt' else 'Gesamt' 

if 'Gruppe' in df_merged_gesamt.columns:
    st.subheader(f"Gruppen-KM-Vergleich ({ranking_period})")

    # Basisdaten: Hängt davon ab, ob der KW-Filter auf 'Gesamt' steht oder nicht
    if selected_kw == 'Gesamt':
        # Verwende die bereits aggregierten Gesamt-KM aus dem Merge-DF
        group_bar_data = df_merged_gesamt.groupby('Gruppe')['KM'].sum().reset_index()
        group_bar_data.columns = ['Gruppe', 'KM']
    else:
        # Filterung auf Basis der tatsächlichen Läufe (df) und erneutes Aggregieren
        df_base = df[df['KW'] == selected_kw].copy()
        group_bar_data = df_base.groupby('Gruppe')['KM'].sum().reset_index()
        group_bar_data.columns = ['Gruppe', 'KM']
        
        # Stellen Sie sicher, dass Gruppen mit 0 KM in dieser KW angezeigt werden
        all_groups = df_merged_gesamt['Gruppe'].unique()
        group_bar_data = group_bar_data.merge(
            pd.DataFrame({'Gruppe': all_groups}), 
            on='Gruppe', 
            how='right'
        ).fillna({'KM': 0})
        
    group_bar_data = group_bar_data.sort_values('KM', ascending=False)
    
    # Highlighting der ausgewählten Gruppe
    group_bar_data['Color'] = group_bar_data['Gruppe'].apply(
        lambda x: PRIMARY_COLOR if x == selected_group else SECONDARY_BACKGROUND_COLOR
    )
    
    fig_group_bar = px.bar(
        group_bar_data,
        x='Gruppe',
        y='KM',
        title=f'Gesamt-KM der Gruppen ({ranking_period})',
        labels={'KM': 'Kilometer', 'Gruppe': 'Gruppe'},
        color='Color', 
        color_discrete_map='identity', 
        template="plotly_white"
    )

    fig_group_bar.update_layout(
        font_family="Arial, sans-serif", title_font_color=TEXT_COLOR, title_font_size=20,
        margin=dict(l=40, r=40, t=60, b=40), 
        xaxis=dict(showgrid=False, title_font_color=TEXT_COLOR, linecolor=TEXT_COLOR, linewidth=1),
        yaxis=dict(gridcolor=SECONDARY_BACKGROUND_COLOR, showgrid=True, title_font_color=TEXT_COLOR, linecolor=TEXT_COLOR, linewidth=1),
        bargap=0.1,
        showlegend=False,
    )
    fig_group_bar.update_xaxes(type='category')

    st.plotly_chart(fig_group_bar, use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True) 

# ==============================================================================
# 7. Diagramm: Name-KM-Vergleich 
# ==============================================================================

st.subheader(f"Einzelwertung: Kilometer-Vergleich nach Name ({ranking_period})")

if 'Name' in df_merged_gesamt.columns:
    
    # Basisdaten: df_merged_gesamt enthält alle Läufer und deren Gesamt-KM
    df_base_runner = df_merged_gesamt.copy()

    # Gruppen-Filter anwenden (kommt aus der Sidebar)
    if selected_group != 'Alle':
        df_base_runner = df_base_runner[df_base_runner['Gruppe'] == selected_group].copy()
    
    # KW-Filter anwenden (Wenn nicht 'Gesamt', müssen wir neu aggregieren)
    if selected_kw != 'Gesamt':
        # 1. Filtern der tatsächlichen Läufe (df)
        df_runs_kw = df[df['KW'] == selected_kw].copy()
        
        # 2. Aggregieren der KM für diese KW
        runner_summary_kw = df_runs_kw.groupby('Name')['KM'].sum().reset_index()
        runner_summary_kw.columns = ['Name', 'KM']
        
        # 3. Mergen mit der kompletten Teilnehmerliste (um 0-KM-Läufer anzuzeigen)
        df_base_runner = df_base_runner[['Name', 'Gruppe']].merge(runner_summary_kw, on='Name', how='left').fillna({'KM': 0})
        df_base_runner = df_base_runner.rename(columns={'KM': 'Gesamt-KM_KW'})
        
        # Gruppen-Filter erneut anwenden (da der Merge die Gruppe nicht übernommen hat, wenn sie 0 KM hatten)
        if selected_group != 'Alle':
            df_base_runner = df_base_runner[df_base_runner['Gruppe'] == selected_group].copy()
        
        # Spaltennamen anpassen
        df_base_runner = df_base_runner.rename(columns={'Gesamt-KM_KW': 'KM'})
    else:
        # Wenn 'Gesamt', verwenden wir die Gesamt-KM aus dem Merge-DF
        df_base_runner = df_base_runner.rename(columns={'KM': 'KM'})

    # Person-Filter anwenden (wenn Name ausgewählt wurde)
    if selected_runner != 'Alle':
        df_base_runner = df_base_runner[df_base_runner['Name'] == selected_runner].copy()

    runner_summary = df_base_runner[['Name', 'KM']].sort_values('KM', ascending=False)
    
    # Highlighting des ausgewählten Läufers
    runner_summary['Color'] = runner_summary['Name'].apply(
        lambda x: PRIMARY_COLOR if x == selected_runner else SECONDARY_BACKGROUND_COLOR
    )

    fig_runner = px.bar(
        runner_summary, 
        x='Name', 
        y='KM',  
        orientation='v', 
        labels={'KM': 'Gesamt-KM', 'Name': 'Name'}, 
        title=f"Einzelwertungen ({ranking_period})",
        color='Color',
        color_discrete_map='identity', 
        template="plotly_white"
    )

    fig_runner.update_layout(
        font_family="Arial, sans-serif", title_font_color=TEXT_COLOR, title_font_size=20,
        margin=dict(l=40, r=40, t=60, b=40), 
        xaxis=dict(
            showgrid=False, title_font_color=TEXT_COLOR, 
            linecolor=TEXT_COLOR, linewidth=1, 
            tickangle=-45 
        ),
        yaxis=dict(
            gridcolor=SECONDARY_BACKGROUND_COLOR, showgrid=True, title_font_color=TEXT_COLOR, 
            linecolor=TEXT_COLOR, linewidth=1
        ),
        bargap=0.1,
        showlegend=False,
    )
    fig_runner.update_xaxes(type='category') 

    st.plotly_chart(fig_runner, use_container_width=True)
else:
    st.info("Die Daten enthalten keine 'Name'-Spalte für diesen Vergleich.")

st.markdown("<br>", unsafe_allow_html=True) 


# ==============================================================================
# 8. BESTENLISTEN (LEADERBOARDS) - PROGRESS BARS
# ==============================================================================

if 'Gruppe' in df_merged_gesamt.columns or 'Name' in df_merged_gesamt.columns:
    st.subheader(f"Aktuelle Bestenlisten ({ranking_period})")
    leaderboard_col1, leaderboard_col2 = st.columns(2)

    # Basisdaten für die Bestenlisten (je nach KW-Filter)
    if selected_kw == 'Gesamt':
        df_leaderboard = df_merged_gesamt.copy()
    else:
        # Aggregieren der KM für diese KW
        df_runs_kw = df[df['KW'] == selected_kw].copy()
        runner_summary_kw = df_runs_kw.groupby('Name')['KM'].sum().reset_index()
        runner_summary_kw.columns = ['Name', 'Gesamt-KM']
        
        # Mergen mit der kompletten Teilnehmerliste (um 0-KM-Läufer anzuzeigen)
        df_leaderboard = df_merged_gesamt[['Name', 'Gruppe']].merge(runner_summary_kw, on='Name', how='left').fillna({'Gesamt-KM': 0})
        df_leaderboard = df_leaderboard.rename(columns={'KM': 'KM_Total'}) # Umbenennung vermeiden Konflikt

    # 1. Gruppen-Bestenliste (Team Leaderboard)
    if 'Gruppe' in df_leaderboard.columns:
        
        # Daten vorbereiten (entweder KM_Total oder KM aus dem Merge-Resultat)
        km_col_name = 'KM' if selected_kw == 'Gesamt' else 'Gesamt-KM'
        
        group_ranking = df_leaderboard.groupby('Gruppe')[km_col_name].sum().reset_index()
        group_ranking.columns = ['Gruppe', 'Gesamt-KM']
        
        # Gruppenfilter aus Sidebar anwenden
        if selected_group != 'Alle':
            group_ranking = group_ranking[group_ranking['Gruppe'] == selected_group]

        group_ranking = group_ranking.sort_values('Gesamt-KM', ascending=False).reset_index(drop=True)
        group_ranking.index = group_ranking.index + 1 
        
        max_group_km = group_ranking['Gesamt-KM'].max() if not group_ranking.empty else 100
        
        with leaderboard_col1:
            st.markdown(f"**🏅 Team-Bestenliste ({ranking_period})**")
            st.dataframe(
                group_ranking, 
                column_order=['Gruppe', 'Gesamt-KM'],
                column_config={
                    'Gesamt-KM': st.column_config.ProgressColumn(
                        "KM", 
                        format="%.1f km", 
                        min_value=0, 
                        max_value=max_group_km, 
                        width='large', 
                        color=PRIMARY_COLOR
                    ),
                },
                use_container_width=True,
            )

    # 2. Name-Bestenliste (Runner Leaderboard)
    if 'Name' in df_leaderboard.columns:
        
        km_col_name = 'KM' if selected_kw == 'Gesamt' else 'Gesamt-KM'
        
        runner_ranking = df_leaderboard.groupby('Name')[km_col_name].sum().reset_index()
        runner_ranking.columns = ['Name', 'Gesamt-KM']
        
        # Gruppen- und Person-Filter anwenden
        if selected_group != 'Alle':
            runner_ranking = df_leaderboard[df_leaderboard['Gruppe'] == selected_group][['Name', km_col_name]].rename(columns={km_col_name: 'Gesamt-KM'})
        if selected_runner != 'Alle':
            runner_ranking = runner_ranking[runner_ranking['Name'] == selected_runner]
        
        
        runner_ranking = runner_ranking.sort_values('Gesamt-KM', ascending=False).reset_index(drop=True)
        
        runner_ranking = runner_ranking.head(10)
        runner_ranking.index = runner_ranking.index + 1 
        
        max_runner_km = runner_ranking['Gesamt-KM'].max() if not runner_ranking.empty else 100
        
        with leaderboard_col2:
            st.markdown(f"**🏃 Top 10 Name-Bestenliste ({ranking_period})**")
            st.dataframe(
                runner_ranking, 
                column_order=['Name', 'Gesamt-KM'],
                column_config={
                    'Gesamt-KM': st.column_config.ProgressColumn(
                        "KM", 
                        format="%.1f km", 
                        min_value=0, 
                        max_value=max_runner_km, 
                        width='large',
                        color=PRIMARY_COLOR
                    ),
                },
                use_container_width=True,
            )

st.markdown("<br>", unsafe_allow_html=True) 

# ==============================================================================
# 9. Diagramm: KW-Entwicklung
# ==============================================================================

st.subheader("9. Kilometer-Entwicklung pro Kalenderwoche (KW)")

# Die Basis für dieses Chart ist der ursprüngliche Lauf-DF (df)
df_base_kw = df.copy()

# Anwenden der Sidebar-Filter auf die Laufdaten (df)
if selected_group != 'Alle':
    df_base_kw = df_base_kw[df_base_kw['Gruppe'] == selected_group].copy()
if selected_runner != 'Alle':
    df_base_kw = df_base_kw[df_base_kw['Name'] == selected_runner].copy()

filter_label = "alle Läufer"
if selected_group != 'Alle' and selected_runner == 'Alle':
    filter_label = f"Gruppe: {selected_group}"
elif selected_runner != 'Alle':
    filter_label = f"Name: {selected_runner}"

if not df_base_kw.empty:
    weekly_summary_chart = df_base_kw.groupby('KW_STR')['KM'].sum()
    weekly_summary_chart = weekly_summary_chart.reindex(CHALLENGE_KWS_STR, fill_value=0).reset_index()
    weekly_summary_chart.columns = ['KW_STR', 'Wochen-KM']
else:
    weekly_summary_chart = pd.DataFrame({'KW_STR': CHALLENGE_KWS_STR, 'Wochen-KM': 0})
    

fig_kw = px.bar(
    weekly_summary_chart, 
    x='KW_STR',
    y='Wochen-KM',
    title=f'Gesamt-KM pro Kalenderwoche für {filter_label} (Gesamtübersicht)',
    labels={'Wochen-KM': 'KM', 'KW_STR': 'Kalenderwoche'},
    color_discrete_sequence=[PRIMARY_COLOR],
    template="plotly_white"
)

fig_kw.update_layout(
    font_family="Arial, sans-serif", title_font_color=TEXT_COLOR, title_font_size=20,
    margin=dict(l=40, r=40, t=60, b=40), 
    xaxis=dict(showgrid=False, tickangle=0, title_font_color=TEXT_COLOR, linecolor=TEXT_COLOR, linewidth=1),
    yaxis=dict(gridcolor=SECONDARY_BACKGROUND_COLOR, showgrid=True, title_font_color=TEXT_COLOR, linecolor=TEXT_COLOR, linewidth=1),
    bargap=0.1, 
)
fig_kw.update_xaxes(type='category', categoryorder='array', categoryarray=CHALLENGE_KWS_STR) 

st.plotly_chart(fig_kw, use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True) 

# ==============================================================================
# 10. DIAGRAMM: Kumulierte Gruppen-Entwicklung (Liniendiagramm) - HIGHLIGHTING
# ==============================================================================

if not group_weekly.empty:
    st.subheader("10. Gruppen-Wettbewerb: Kumulierte Kilometer-Entwicklung (Statisch)")
    
    # Farbzuweisung für Highlighting
    if selected_group != 'Alle' and selected_group in group_weekly['Gruppe'].unique():
        color_map = {g: PRIMARY_COLOR if g == selected_group else 'lightgrey' for g in group_weekly['Gruppe'].unique()}
    else:
        # Wenn "Alle" gewählt, verwende Standard-Farbpalette
        color_map = {g: c for g, c in zip(group_weekly['Gruppe'].unique(), px.colors.qualitative.Bold)}
        
    
    fig_group_cum = px.line(
        group_weekly, 
        x='KW_STR',
        y='Kumulierte_KM',
        color='Gruppe', 
        markers=True,
        title='Kumulierte Gruppen-KM nach Kalenderwoche (Gesamt)',
        labels={'Kumulierte_KM': 'Kumulierte KM', 'KW_STR': 'Kalenderwoche', 'Gruppe': 'Gruppe'},
        color_discrete_map=color_map, 
        template="plotly_white" 
    )
    
    # Anpassung der Linienstärke für die ausgewählte Gruppe
    if selected_group != 'Alle':
        for i, trace in enumerate(fig_group_cum.data):
            if trace.name == selected_group:
                trace.line.width = 4
                trace.marker.size = 10
            else:
                trace.line.width = 1.5
                trace.line.dash = 'dot' 
                trace.marker.size = 5


    fig_group_cum.update_layout(
        font_family="Arial, sans-serif", title_font_color=TEXT_COLOR, title_font_size=20,
        margin=dict(l=40, r=40, t=60, b=40), 
        xaxis=dict(showgrid=False, title_font_color=TEXT_COLOR, linecolor=TEXT_COLOR, linewidth=1),
        yaxis=dict(gridcolor=SECONDARY_BACKGROUND_COLOR, showgrid=True, title_font_color=TEXT_COLOR, linecolor=TEXT_COLOR, linewidth=1),
        legend_title_text='Gruppe',
        hoverlabel=dict(bgcolor="white", font_size=14, font_family="Arial, sans-serif")
    )
    fig_group_cum.update_xaxes(type='category', categoryorder='array', categoryarray=CHALLENGE_KWS_STR) 

    st.plotly_chart(fig_group_cum, use_container_width=True)

st.markdown("<br>", unsafe_allow_html=True) 


# ==============================================================================
# 11. Detailtabelle
# ==============================================================================

st.subheader(f"Detailübersicht (Gefilterte Daten)")

# Die Detailtabelle zeigt die aggregierten Daten mit 0-KM-Läufern (df_merged_gesamt)
# und wird nur auf Name und Gruppe gefiltert, nicht auf KW, da hier nur die Gesamt-KM stehen.
df_detail_display = df_merged_gesamt.copy()

if selected_group != 'Alle':
    df_detail_display = df_detail_display[df_detail_display['Gruppe'] == selected_group].copy()

if selected_runner != 'Alle':
    df_detail_display = df_detail_display[df_detail_display['Name'] == selected_runner].copy()

# Wenn KW != Gesamt, müssen wir die KM Spalte ersetzen (was im Leaderboard passiert, aber hier nicht sinnvoll ist)
# Wir zeigen hier nur die Gesamt-KM, da die Tabelle sonst extrem komplex wird.
df_detail_display = df_detail_display.sort_values('KM', ascending=False)
df_detail_display = df_detail_display.rename(columns={'KM': 'Gesamt-KM'})


st.dataframe(df_detail_display, use_container_width=True, hide_index=True)
