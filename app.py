import streamlit as st
import pandas as pd
# import json # Nicht mehr benötigt
import gspread
# from oauth2client.service_account import ServiceAccountCredentials # Nicht mehr benötigt
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import pytz # Importiert für die korrekte Zeitzonenbehandlung

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

# Google Sheets Konfiguration (ID und Worksheets)
SHEET_ID = "1z-mPq_eqFDQvMA-sZ6TkDoPN-x8FTCu2brWd1PkHO3I"
WORKSHEET_NAME_LAUF = "Laufdaten" # Das Sheet mit den eingetragenen Läufen
WORKSHEET_NAME_TEILNEHMER = "Teilnehmer" # Das Sheet mit der Teilnehmerliste

# Zeitzonen- und Zeitstempel-Konfiguration
TIMEZONE = pytz.timezone('Europe/Berlin')
LAST_LOAD_TIME = datetime.now(TIMEZONE).strftime("%d.%m.%Y, %H:%M Uhr")

# Initialisierung des gspread-Clients (MODERNISIERT)
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
    Lädt die Teilnehmerliste und die Laufdaten.
    Gibt beide DataFrames zurück.
    """
    
    # 1. TEILNEHMERLISTE LADEN ('Teilnehmer' Sheet)
    try:
        wks_teilnehmer = gc.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME_TEILNEHMER)
        df_teilnehmer = pd.DataFrame(wks_teilnehmer.get_all_records())
        
        # Validierung des Teilnehmer-Sheets
        if 'Name' not in df_teilnehmer.columns or 'Gruppe' not in df_teilnehmer.columns:
            st.error("Fehler: Das 'Teilnehmer'-Sheet muss die Spalten 'Name' und 'Gruppe' enthalten.")
            return pd.DataFrame(), pd.DataFrame() 
            
    except Exception as e:
        st.error(f"Fehler beim Laden der Teilnehmerliste (Sheet '{WORKSHEET_NAME_TEILNEHMER}'). Prüfen Sie, ob es existiert und korrekt benannt ist. {e}")
        return pd.DataFrame(), pd.DataFrame()

    # 2. LAUFDATEN LADEN ('Laufdaten' Sheet)
    try:
        wks_laufdaten = gc.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME_LAUF) 
        df_laufdaten = pd.DataFrame(wks_laufdaten.get_all_records())
        
    except Exception as e:
        st.warning(f"Warnung: Fehler beim Laden der Laufdaten (Sheet '{WORKSHEET_NAME_LAUF}'). Führe mit leeren Laufdaten fort: {e}")
        # Erstelle einen leeren DF mit erwarteten Spalten für den Merge
        df_laufdaten = pd.DataFrame({'Name': [], 'KM': [], 'Datum': [], 'KW': []})

    return df_teilnehmer, df_laufdaten 
# Ende der load_data Funktion


# ==============================================================================
# 2. DATEN VORBEREITEN & BEREINIGEN (Erweiterte Transformation)
# ==============================================================================

@st.cache_data
def transform_data(df_teilnehmer, df_laufdaten):
    """Konvertiert Datentypen, berechnet Aggregationen und führt die Daten zusammen."""
    
    # 1. Laufdaten bereinigen und vorbereiten (df_runs)
    df_runs = df_laufdaten.copy()
    df_runs.columns = [col.strip() for col in df_runs.columns]
    
    # Sicherstellen, dass die Spalte KM vorhanden ist, auch wenn leer
    if 'KM' not in df_runs.columns:
         df_runs['KM'] = 0.0
    else:
         df_runs['KM'] = pd.to_numeric(df_runs['KM'], errors='coerce').fillna(0)
         
    df_runs['Datum'] = pd.to_datetime(df_runs['Datum'], format='%d.%m.%Y', errors='coerce')
    
    # KW behandeln
    if 'KW' not in df_runs.columns:
        df_runs['KW'] = df_runs['Datum'].dt.isocalendar().week.astype('Int64')
    else:
        df_runs['KW'] = pd.to_numeric(df_runs['KW'], errors='coerce', downcast='integer')

    df_runs['KW_STR'] = df_runs['KW'].astype(str)
        
    # Filtern nach Challenge-KW
    df_runs = df_runs[df_runs['KW_STR'].isin(CHALLENGE_KWS_STR)].copy()

    # ----------------------------------------------------------------------
    # 2. Zusammenführen der Teilnehmer (df_merged_gesamt für 0-KM-Läufer)
    # ----------------------------------------------------------------------
    
    # Aggregiere die KM pro Läufer aus den Laufdaten (df_runs)
    df_summe_km = df_runs.groupby('Name', as_index=False)['KM'].sum()
    
    # Left-Join, um ALLE Teilnehmer aus der Liste zu behalten
    df_merged_gesamt = pd.merge(df_teilnehmer, df_summe_km, on='Name', how='left')
    df_merged_gesamt['KM'] = df_merged_gesamt['KM'].fillna(0) # 0-KM-Läufer bekommen 0 KM
    
    # ----------------------------------------------------------------------
    # 3. Aggregation für KW-Diagramm (Gesamt)
    # ----------------------------------------------------------------------
    weekly_summary = df_runs.groupby('KW_STR')['KM'].sum().reset_index()
    weekly_summary.rename(columns={'KM': 'Wochen-KM'}, inplace=True)
    
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
    # 4. Aggregation und KUMULIERUNG für Gruppen-Diagramm 
    # ----------------------------------------------------------------------
    group_weekly = pd.DataFrame() 
    
    # Sicherstellen, dass die Laufdaten nicht leer sind und die Teilnehmerdaten die Gruppe enthalten
    if not df_runs.empty and 'Gruppe' in df_teilnehmer.columns:
        
        # Laufdaten um Gruppenzugehörigkeit erweitern
        df_runs_with_group = pd.merge(df_runs, df_teilnehmer[['Name', 'Gruppe']], on='Name', how='left')
        
        # Sicherheitscheck: Falls der Merge fehlschlägt und 'Gruppe' fehlt
        if 'Gruppe' not in df_runs_with_group.columns:
            # Dies sollte nur passieren, wenn df_teilnehmer eine leere Gruppe-Spalte hatte,
            # was der obige Check verhindert, aber zur Sicherheit:
            return df_runs, weekly_summary, group_weekly, df_merged_gesamt
        
        # Entferne Läufe von Personen, die keiner Gruppe zugeordnet werden konnten (Gruppe ist NaN)
        df_runs_with_group.dropna(subset=['Gruppe'], inplace=True)

        # Überprüfe erneut, ob nach dem Aufräumen noch Daten übrig sind
        if not df_runs_with_group.empty:
            
            # Setze die KW_STR Spalte als geordnete Kategorie für die Kumulierung
            df_runs_with_group['KW_STR'] = pd.Categorical(
                df_runs_with_group['KW_STR'], 
                categories=CHALLENGE_KWS_STR,
                ordered=True
            )

            # Wöchentliche KM pro Gruppe
            group_weekly = df_runs_with_group.groupby(['Gruppe', 'KW_STR'], observed=True)['KM'].sum().reset_index()
            
            # Kumuliere die KM pro Gruppe
            group_weekly['Kumulierte_KM'] = group_weekly.groupby('Gruppe')['KM'].cumsum()
        
    return df_runs, weekly_summary, group_weekly, df_merged_gesamt

# Daten laden und transformieren
df_teilnehmer_raw, df_laufdaten_raw = load_data()
df_runs, weekly_summary, group_weekly, df_merged_gesamt = transform_data(df_teilnehmer_raw, df_laufdaten_raw)

# Sicherheits-Check
if df_teilnehmer_raw.empty:
    st.info("Fehler: Die Teilnehmerliste ist leer. Dashboard kann nicht geladen werden.")
    st.stop()


# ==============================================================================
# 3. DASHBOARD VISUALISIERUNG & FILTER
# ==============================================================================

# --- Sidebar (Logo und Filter) ---
with st.sidebar:
    # ... (Code für Logo und Titel bleibt gleich) ...
    try:
        st.image("logo.png", width=180)
    except FileNotFoundError:
        st.warning("Logo 'logo.png' nicht gefunden.")

    st.markdown(f"<h1 style='text-align: center; color: {PRIMARY_COLOR}; font-size: 2.2em;'>Laufchallenge</h1>", unsafe_allow_html=True)
    st.markdown("---")
    st.subheader("Filter")

    # Wichtig: df_filtered basiert jetzt auf df_merged_gesamt (vollständige Teilnehmerliste)
    df_filtered_leaderboard = df_merged_gesamt.copy() 

    # 1. Gruppen-Filter
    selected_group = 'Alle'
    groups = df_merged_gesamt['Gruppe'].unique()
    selected_group = st.selectbox("1. Wähle Gruppe", ['Alle'] + sorted(list(groups)))

    if selected_group != 'Alle':
        # Filterung des Leaderboard-DF
        df_filtered_leaderboard = df_filtered_leaderboard[df_filtered_leaderboard['Gruppe'] == selected_group].copy() 

    # 2. Personen-Filter
    selected_runner = 'Alle'
    # Die Runner-Liste basiert auf der bereits gefilterten Gruppe
    runners_in_group = df_filtered_leaderboard['Name'].unique()
    selected_runner = st.selectbox("2. Wähle Name", ['Alle'] + sorted(list(runners_in_group)))

    if selected_runner != 'Alle':
        # Filterung des Leaderboard-DF
        df_filtered_leaderboard = df_filtered_leaderboard[df_filtered_leaderboard['Name'] == selected_runner].copy()

    # 3. KW-Filter (Für Bestenlisten/Bar-Charts)
    selected_kw = 'Gesamt'
    kw_options = ['Gesamt'] + CHALLENGE_KWS
        
    selected_kw = st.selectbox(
        "3. Wähle Kalenderwoche (KW) für Bestenlisten",
        options=kw_options,
        index=0
    )

ranking_period = selected_kw if selected_kw != 'Gesamt' else 'Gesamt'

# ==============================================================================
# 4. HAUPTBEREICH DES DASHBOARDS (MIT VOLLSTÄNDIGER DATENBASIS)
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
    
    gesamt_km_total = df_merged_gesamt['KM'].sum() # KM aller Teilnehmer (inkl. 0)
    anzahl_läufe_total = df_runs.shape[0] # Anzahl Läufe basiert auf dem reinen Laufdaten-Sheet

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
    col3.metric(
        label="Anzahl Gruppen", 
        value=df_merged_gesamt['Gruppe'].nunique(),
        help="Anzahl der Teams, die an der Challenge teilnehmen."
    )

st.markdown("<br>", unsafe_allow_html=True) 

# ==============================================================================
# 5. REKORDE & BESTLEISTUNGEN (STATISCH - BASIERT AUF df_runs)
# ==============================================================================
# Nur zeigen, wenn es mindestens einen Lauf gibt
if not df_runs.empty and df_runs['KM'].sum() > 0: 
    with st.container(border=True):
        st.markdown(f"<h4 style='color: {PRIMARY_COLOR};'>👑 Rekorde & Bestleistungen</h4>", unsafe_allow_html=True)
        record_col1, record_col2 = st.columns(2)

        # --- 1. Längste Einheit ---
        max_km_entry = df_runs.loc[df_runs['KM'].idxmax()]
        max_km = max_km_entry['KM']
        max_km_runner = max_km_entry['Name']
        
        max_km_date = max_km_entry['Datum'].strftime('%d.%m.') if pd.notna(max_km_entry['Datum']) else "Datum unbekannt"
        
        with record_col1:
            st.metric(
                label="🥇 Längste Einzeldistanz",
                value=f"{max_km:,.1f} km",
                help="Die höchste Kilometerzahl, die ein Läufer in einem einzigen Eintrag gemeldet hat."
            )
            st.caption(f"**Rekordhalter:** {max_km_runner} ({max_km_date})")

        # --- 2. Fleißigster Läufer (Runs) ---
        runner_runs = df_runs.groupby('Name')['KM'].count()
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
# 6. DIAGRAMM: Gruppen-KM-Vergleich (BASIERT AUF df_merged_gesamt)
# ==============================================================================

st.subheader(f"Gruppen-KM-Vergleich ({ranking_period})")

# Basisdaten: Hängt davon ab, ob der KW-Filter auf 'Gesamt' steht oder nicht
df_base_chart = df_merged_gesamt.copy() # Start mit allen Teilnehmern und ihren Gesamt-KM

if selected_kw == 'Gesamt':
    # Verwende die bereits aggregierten Gesamt-KM aus dem Merge-DF (KM-Spalte)
    group_bar_data = df_base_chart.groupby('Gruppe')['KM'].sum().reset_index()
    group_bar_data.columns = ['Gruppe', 'KM']
else:
    # Neu-Aggregation für die spezifische KW aus df_runs
    df_runs_kw = df_runs[df_runs['KW'] == selected_kw].copy()
    group_sum_kw = df_runs_kw.groupby('Gruppe')['KM'].sum().reset_index()
    
    # Merge, um 0-KM-Gruppen aus der Teilnehmerliste zu zeigen
    group_bar_data = df_merged_gesamt[['Gruppe']].drop_duplicates().merge(
        group_sum_kw, on='Gruppe', how='left'
    ).fillna({'KM': 0})
    group_bar_data.columns = ['Gruppe', 'KM']
    
    
# Anwenden des Gruppen-Filters aus der Sidebar auf die Chart-Daten
if selected_group != 'Alle':
    group_bar_data = group_bar_data[group_bar_data['Gruppe'] == selected_group].copy()
    
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
# 7. Diagramm: Name-KM-Vergleich (BASIERT AUF df_merged_gesamt)
# ==============================================================================

st.subheader(f"Einzelwertung: Kilometer-Vergleich nach Name ({ranking_period})")

# Basisdaten: df_merged_gesamt enthält alle Läufer und deren Gesamt-KM
df_base_runner = df_merged_gesamt.copy()
    
# 1. KW-Filter anwenden
if selected_kw != 'Gesamt':
    # Filtern und Aggregieren auf Basis der reinen Läufe (df_runs)
    df_runs_kw = df_runs[df_runs['KW'] == selected_kw].copy()
    runner_summary_kw = df_runs_kw.groupby('Name')['KM'].sum().reset_index()
    
    # Mergen mit der kompletten Teilnehmerliste (um 0-KM-Läufer in dieser KW anzuzeigen)
    df_base_runner = df_merged_gesamt[['Name', 'Gruppe']].merge(runner_summary_kw, on='Name', how='left').fillna({'KM': 0})
else:
    # Wenn 'Gesamt', verwenden wir die Gesamt-KM aus dem Merge-DF
    df_base_runner = df_merged_gesamt.rename(columns={'KM': 'KM'})


# 2. Gruppen-Filter anwenden (kommt aus der Sidebar)
if selected_group != 'Alle':
    df_base_runner = df_base_runner[df_base_runner['Gruppe'] == selected_group].copy()

# 3. Person-Filter anwenden (wenn Name ausgewählt wurde)
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

st.markdown("<br>", unsafe_allow_html=True) 

# ==============================================================================
# 8. BESTENLISTEN (LEADERBOARDS) - PROGRESS BARS (BASIERT AUF df_filtered_leaderboard)
# ==============================================================================

st.subheader(f"Aktuelle Bestenlisten ({ranking_period})")
leaderboard_col1, leaderboard_col2 = st.columns(2)

# Wichtig: Wir müssen df_filtered_leaderboard auf Basis des KW-Filters neu berechnen,
# da die Sidebar-Filterung nur auf 'Gesamt' KM angewendet wurde.

if selected_kw == 'Gesamt':
    df_leaderboard = df_merged_gesamt.rename(columns={'KM': 'Gesamt-KM'}).copy()
else:
    # Führe Aggregation für die spezifische KW durch
    df_runs_kw = df_runs[df_runs['KW'] == selected_kw].copy()
    runner_summary_kw = df_runs_kw.groupby('Name')['KM'].sum().reset_index()
    
    # Mergen mit der kompletten Teilnehmerliste (um 0-KM-Läufer in dieser KW anzuzeigen)
    df_leaderboard = df_merged_gesamt[['Name', 'Gruppe']].merge(runner_summary_kw, on='Name', how='left').fillna({'KM': 0})
    df_leaderboard = df_leaderboard.rename(columns={'KM': 'Gesamt-KM'})

# Filteranwendung auf df_leaderboard (damit sie konsistent zur Sidebar sind)
if selected_group != 'Alle':
    df_leaderboard = df_leaderboard[df_leaderboard['Gruppe'] == selected_group].copy()
if selected_runner != 'Alle':
    df_leaderboard = df_leaderboard[df_leaderboard['Name'] == selected_runner].copy()


# 1. Gruppen-Bestenliste (Team Leaderboard)
group_ranking = df_leaderboard.groupby('Gruppe')['Gesamt-KM'].sum().reset_index()
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
runner_ranking = df_leaderboard[['Name', 'Gesamt-KM']].copy()
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

df_base_kw = df_runs.copy() # Start mit den reinen Laufdaten

# Filter auf die reinen Laufdaten anwenden
if selected_group != 'Alle':
    # Um nach Gruppe zu filtern, müssen wir die Gruppenzugehörigkeit hinzufügen
    df_base_kw = pd.merge(df_base_kw, df_merged_gesamt[['Name', 'Gruppe']], on='Name', how='left')
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
# 10. DIAGRAMM: Kumulierte Gruppen-Entwicklung (Liniendiagramm)
# ==============================================================================

if not group_weekly.empty:
    st.subheader("10. Gruppen-Wettbewerb: Kumulierte Kilometer-Entwicklung (Statisch)")
    
    # Anwenden des Gruppenfilters (für Highlighting und Chart-Inhalt)
    group_weekly_filtered = group_weekly.copy()
    if selected_group != 'Alle':
        group_weekly_filtered = group_weekly_filtered[group_weekly_filtered['Gruppe'] == selected_group].copy()
    
    # Farbzuweisung für Highlighting
    if selected_group != 'Alle' and selected_group in group_weekly['Gruppe'].unique():
        # Führe Highlighting nur im großen DF durch, damit die grauen Linien sichtbar sind
        color_map = {g: PRIMARY_COLOR if g == selected_group else 'lightgrey' for g in group_weekly['Gruppe'].unique()}
        data_source = group_weekly # Ungefilterte Daten für die grauen Linien
    else:
        # Wenn "Alle" gewählt, verwende Standard-Farbpalette auf ungefilterten Daten
        color_map = {g: c for g, c in zip(group_weekly['Gruppe'].unique(), px.colors.qualitative.Bold)}
        data_source = group_weekly
        
    
    fig_group_cum = px.line(
        data_source, 
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

st.subheader(f"Detailübersicht (Gefilterte Läufer)")

# Die Detailtabelle zeigt die aggregierten Daten mit 0-KM-Läufern (df_merged_gesamt)
df_detail_display = df_merged_gesamt.copy()

# Filter anwenden
if selected_group != 'Alle':
    df_detail_display = df_detail_display[df_detail_display['Gruppe'] == selected_group].copy()

if selected_runner != 'Alle':
    df_detail_display = df_detail_display[df_detail_display['Name'] == selected_runner].copy()

# Die KM-Spalte ist bereits die aggregierte Gesamt-KM (oder 0)
df_detail_display = df_detail_display.sort_values('KM', ascending=False)
df_detail_display = df_detail_display.rename(columns={'KM': 'Gesamt-KM'})


st.dataframe(df_detail_display, use_container_width=True, hide_index=True)


