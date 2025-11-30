import streamlit as st
import pandas as pd
import json
import gspread 
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
import plotly.graph_objects as go 
from datetime import datetime 

# ==============================================================================
# 0. KONFIGURATION & GLOBALE VARIABLEN
# ==============================================================================

# Branding-Farben des Suchsdorfer SV
PRIMARY_COLOR = "#002060"  
TEXT_COLOR = "#212121"    
BACKGROUND_COLOR = "#FFFFFF" 
SECONDARY_BACKGROUND_COLOR = "#F0F2F6" 

# Challenge Zeitraum KWs
CHALLENGE_KWS = [45, 46, 47, 48, 49, 50, 51, 52, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
CHALLENGE_KWS_STR = [str(kw) for kw in CHALLENGE_KWS]

st.set_page_config(
    page_title="Laufchallenge Dashboard | Suchsdorfer SV",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Google Sheets Zugangsdaten
SHEET_ID = "1z-mPq_eqFDQvMA-sZ6TkDoPN-x8FTCu2brWd1PkHO3I"
WORKSHEET_NAME = "Laufdaten" 
# JSON_PATH wurde entfernt, da wir Streamlit Secrets verwenden

# Zeitstempel der letzten Datenladung (Wichtig: Global definiert zur Behebung des NameError)
LAST_LOAD_TIME = datetime.now().strftime("%d.%m.%Y, %H:%M Uhr")


# ==============================================================================
# 1. DATEN LADEN (Caching & gspread) - ANGEPASST FÜR STREAMLIT SECRETS
# ==============================================================================

@st.cache_data(ttl=86400)
def load_data():
    """Lädt Daten aus Google Sheets über gspread und JSON-Key (jetzt aus Streamlit Secrets)."""
    try:
        # Sicherstellen, dass die Keys in den Secrets vorhanden sind
        if 'gcp_service_account' not in st.secrets:
             st.error("❌ Die Secrets für den Google Service Account wurden nicht gefunden. Bitte überprüfen Sie die Streamlit Secrets Box.")
             st.stop()
             
        # Erstelle ein Credential-Objekt direkt aus den Secrets (wichtig: from_json_keyfile_dict verwenden)
        creds_info = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            creds_info, 
            ['https://www.googleapis.com/auth/spreadsheets']
        )
        
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID)
        worksheet = sheet.worksheet(WORKSHEET_NAME)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        return df
    except Exception as e:
        st.error("❌ Ein Fehler ist beim Laden der Daten aufgetreten. Haben Sie die Sheets-ID korrekt hinterlegt und den Service Account zum Google Sheet hinzugefügt?")
        st.exception(e)
        st.stop()

# ==============================================================================
# 2. DATEN VORBEREITEN & BEREINIGEN
# ==============================================================================

@st.cache_data
def transform_data(df):
    """Konvertiert Datentypen und berechnet Aggregationen."""
    df.columns = [col.strip() for col in df.columns]
    
    if 'KM' not in df.columns:
        st.error("Spalte 'KM' nicht in der Google Tabelle gefunden.")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame() 
        
    df['KM'] = pd.to_numeric(df['KM'], errors='coerce')
    df['Datum'] = pd.to_datetime(df['Datum'], format='%d.%m.%Y', errors='coerce')
    df['KW'] = pd.to_numeric(df['KW'], errors='coerce', downcast='integer')
    df['KW_STR'] = df['KW'].astype(str)
    
    # ----------------------------------------------------------------------
    # 1. Aggregation für KW-Diagramm (Gesamt)
    # ----------------------------------------------------------------------
    weekly_summary = df.groupby('KW_STR')['KM'].sum().reset_index()
    weekly_summary.rename(columns={'KM': 'Wochen-KM'}, inplace=True)
    
    # ----------------------------------------------------------------------
    # 2. Aggregation und KUMULIERUNG für Gruppen-Diagramm (STATISCHE DATEN)
    # ----------------------------------------------------------------------
    if 'Gruppe' in df.columns:
        df_filtered_kws = df[df['KW_STR'].isin(CHALLENGE_KWS_STR)].copy() 

        # KORREKTUR: Setze die KW_STR Spalte als geordnete Kategorie
        df_filtered_kws['KW_STR'] = pd.Categorical(
            df_filtered_kws['KW_STR'], 
            categories=CHALLENGE_KWS_STR,
            ordered=True
        )

        # 1. Wöchentliche KM pro Gruppe
        group_weekly = df_filtered_kws.groupby(['Gruppe', 'KW_STR'], observed=True)['KM'].sum().reset_index()
        
        # 2. Sortiere nach Gruppe und dann nach der korrekten kategorialen KW_STR
        group_weekly = group_weekly.sort_values(['Gruppe', 'KW_STR'])
        
        # 3. Kumuliere die KM pro Gruppe
        group_weekly['Kumulierte_KM'] = group_weekly.groupby('Gruppe')['KM'].cumsum()
    else:
        group_weekly = pd.DataFrame()

    return df, weekly_summary, group_weekly

df_raw = load_data()
df, weekly_summary, group_weekly = transform_data(df_raw)

if df.empty or df['KM'].sum() == 0:
    st.info("Keine gültigen Laufdaten zur Visualisierung gefunden.")
    st.stop()

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

    df_filtered = df.copy() # Kopie des gesamten Datensatzes für Filterung

    # 1. Gruppen-Filter (Wird für df_filtered angewendet)
    selected_group = 'Alle'
    if 'Gruppe' in df.columns:
        groups = df['Gruppe'].unique()
        selected_group = st.selectbox("1. Wähle Gruppe", ['Alle'] + sorted(list(groups)))

        if selected_group != 'Alle':
            df_filtered = df_filtered[df_filtered['Gruppe'] == selected_group].copy() 

    # 2. Personen-Filter (Wird für df_filtered angewendet)
    selected_runner = 'Alle'
    if 'Name' in df_filtered.columns: 
        runners = df_filtered['Name'].unique()
        selected_runner = st.selectbox("2. Wähle Name", ['Alle'] + sorted(list(runners))) 

        if selected_runner != 'Alle':
            df_filtered = df_filtered[df_filtered['Name'] == selected_runner].copy()
        
    # 3. KW-Filter (Wird für df_filtered angewendet)
    selected_kw = 'Gesamt'
    if 'KW' in df_filtered.columns:
        kw_options = ['Gesamt'] + CHALLENGE_KWS
        
        selected_kw = st.selectbox(
            "3. Wähle Kalenderwoche (KW)",
            options=kw_options,
            index=0
        )

        # Anwendung des KW-Filters auf df_filtered (für Bestenlisten und Detailtabelle)
        if selected_kw != 'Gesamt':
            df_filtered = df_filtered[df_filtered['KW'] == selected_kw]
        
        weekly_summary_filtered = df_filtered.groupby('KW_STR')['KM'].sum().reset_index()
        weekly_summary_filtered.rename(columns={'KM': 'Wochen-KM'}, inplace=True)
        
        weekly_summary_filtered['KW_STR'] = pd.Categorical(
            weekly_summary_filtered['KW_STR'], 
            categories=CHALLENGE_KWS_STR,
            ordered=True
        )
        weekly_summary_filtered = weekly_summary_filtered.dropna(subset=['KW_STR']).sort_values('KW_STR')
        
    else:
        weekly_summary_filtered = weekly_summary.copy()

# ==============================================================================
# 4. HAUPTBEREICH DES DASHBOARDS
# ==============================================================================

st.markdown(
    f"""<h1 style='color: {PRIMARY_COLOR};'>Laufchallenge Übersicht</h1>""", 
    unsafe_allow_html=True
)
st.caption(f"Letzte Aktualisierung der Daten: **{LAST_LOAD_TIME}**") # KORRIGIERT: LAST_LOAD_TIME ist jetzt global

# --- 4. Metriken (Fortschritt) ---
with st.container(border=True):
    st.markdown(f"<h4 style='color: {PRIMARY_COLOR};'>🚀 Aktueller Fortschritt (Gesamt)</h4>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    
    gesamt_km_total = df['KM'].sum()
    anzahl_läufe_total = df.shape[0]

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
    if 'Gruppe' in df.columns:
        col3.metric(
            label="Anzahl Gruppen", 
            value=df['Gruppe'].nunique(),
            help="Anzahl der Teams, die an der Challenge teilnehmen."
        )

st.markdown("<br>", unsafe_allow_html=True) 

# ==============================================================================
# 5. REKORDE & BESTLEISTUNGEN (STATISCH)
# ==============================================================================

if 'Name' in df.columns:
    with st.container(border=True): # Einheitlicher Rahmen
        st.markdown(f"<h4 style='color: {PRIMARY_COLOR};'>👑 Rekorde & Bestleistungen</h4>", unsafe_allow_html=True)
        record_col1, record_col2 = st.columns(2)

        # --- 1. Längste Einheit ---
        max_km_entry = df.loc[df['KM'].idxmax()]
        max_km = max_km_entry['KM']
        max_km_runner = max_km_entry['Name']
        max_km_date = max_km_entry['Datum'].strftime('%d.%m.')
        
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

if 'Gruppe' in df.columns:
    st.subheader(f"Gruppen-KM-Vergleich ({ranking_period})")

    df_base = df.copy()
    all_groups = sorted(list(df['Gruppe'].unique())) 

    if selected_kw != 'Gesamt':
        df_base = df_base[df_base['KW'] == selected_kw]

    if not df_base.empty:
        group_bar_data = df_base.groupby('Gruppe')['KM'].sum()
        group_bar_data = group_bar_data.reindex(all_groups, fill_value=0).reset_index()
        group_bar_data.columns = ['Gruppe', 'KM']
        group_bar_data = group_bar_data.sort_values('KM', ascending=False)
    else:
        group_bar_data = pd.DataFrame({'Gruppe': all_groups, 'KM': 0})
    
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

if 'Name' in df.columns:
    df_base_runner = df.copy()

    if selected_group != 'Alle':
        df_base_runner = df_base_runner[df_base_runner['Gruppe'] == selected_group].copy()
    
    if selected_kw != 'Gesamt':
        df_base_runner = df_base_runner[df_base_runner['KW'] == selected_kw].copy()
    
    runner_summary = df_base_runner.groupby('Name')['KM'].sum().reset_index()
    runner_summary = runner_summary.sort_values('KM', ascending=False)
    
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

if 'Gruppe' in df_filtered.columns or 'Name' in df_filtered.columns:
    st.subheader(f"Aktuelle Bestenlisten ({ranking_period})")
    leaderboard_col1, leaderboard_col2 = st.columns(2)

    # 1. Gruppen-Bestenliste (Team Leaderboard)
    if 'Gruppe' in df_filtered.columns:
        group_ranking = df_filtered.groupby('Gruppe')['KM'].sum().reset_index()
        group_ranking.columns = ['Gruppe', 'Gesamt-KM']
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
    if 'Name' in df_filtered.columns:
        runner_ranking = df_filtered.groupby('Name')['KM'].sum().reset_index()
        runner_ranking.columns = ['Name', 'Gesamt-KM']
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

df_base_kw = df.copy()

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
st.dataframe(df_filtered, use_container_width=True, hide_index=True)

