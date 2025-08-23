import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from google.cloud import storage
from datetime import datetime, timedelta
import os
import re

# Streamlit page configuration
st.set_page_config(page_title="Weather MSLP Analysis", layout="wide")

# Title
st.title("🌊 MSLP Analysis: Time Series and South China Sea Map")

# Initialize GCS client
client = storage.Client()
bucket_name = "walter-weather-2"
prefixes = ["gencast_mslp/", "gefs_mslp/"]

@st.cache_data
def list_csv_files(prefix):
    try:
        bucket = client.get_bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=prefix)
        pattern = r"mslp_\d{8}(12|00)\.csv$"
        csv_files = [blob.name for blob in blobs if re.match(pattern, blob.name.split('/')[-1])]
        dates = []
        for file in csv_files:
            date_str = file.split('/')[-1].replace('mslp_', '').replace('.csv', '')
            date = datetime.strptime(date_str, '%Y%m%d%H')
            dates.append((file, date.strftime('%Y-%m-%d %H:%M')))
        return sorted(dates, key=lambda x: x[1])
    except Exception as e:
        st.error(f"Error listing files from GCS: {e}")
        return []

@st.cache_data
def load_data(file_path):
    try:
        bucket = client.get_bucket(bucket_name)
        blob = bucket.blob(file_path)
        data = blob.download_as_string()
        df = pd.read_csv(pd.io.common.StringIO(data.decode('utf-8')))
        return df
    except Exception as e:
        st.error(f"Error loading data from GCS: {e}")
        return None

# Sidebar for filtering
st.sidebar.header("Filter Options")

# Date selection
all_dates = set()
for prefix in prefixes:
    dataset = prefix.split('_')[0].capitalize()
    csv_files = list_csv_files(prefix)
    all_dates.update(date for _, date in csv_files)

date_options = sorted(list(all_dates))
selected_date = st.sidebar.selectbox("Select Date", options=date_options)

# Load data for both datasets
gencast_df = None
gefs_df = None
for prefix in prefixes:
    dataset = prefix.split('_')[0].capitalize()
    csv_files = list_csv_files(prefix)
    selected_file = next((file for file, date in csv_files if date == selected_date), None)
    if selected_file:
        df = load_data(selected_file)
        if df is not None:
            if dataset == "Gencast":
                df['Dataset'] = "Gencast"
                df['Ensemble'] = df['Sample']
                df['Forecast_Datetime'] = df.apply(
                    lambda row: pd.to_datetime(row['Datetime']) + timedelta(hours=row['Time_Step'] * 12), axis=1)
                gencast_df = df
            else:  # GEFS
                df['Dataset'] = "GEFS"
                df['Ensemble'] = df['Member']
                df['Forecast_Datetime'] = pd.to_datetime(df['Timestamp'])
                gefs_df = df

# Combine datasets
if gencast_df is not None and gefs_df is not None:
    df = pd.concat([gencast_df, gefs_df], ignore_index=True)
elif gencast_df is not None:
    df = gencast_df
elif gefs_df is not None:
    df = gefs_df
else:
    df = None

if df is not None:
    # Ensemble selection (no default)
    all_ensembles = sorted(df['Ensemble'].unique())
    selected_ensembles = st.sidebar.multiselect("Select Ensembles", options=all_ensembles, default=[])
    
    # Statistics selection for time series (max 2)
    stat_options = ["25th Percentile", "75th Percentile"]
    selected_stats = st.sidebar.multiselect("Select Statistics to Plot (Max 2)", 
                                           options=stat_options, 
                                           default=[], 
                                           max_selections=2)
    
    # Latitude and Longitude filters for map
    st.sidebar.subheader("Map Filters (South China Sea)")
    lat_min, lat_max = st.sidebar.slider("Latitude Range (0-25°N)", 
                                         min_value=0.0, max_value=25.0, 
                                         value=(0.0, 25.0), step=0.5)
    lon_min, lon_max = st.sidebar.slider("Longitude Range (100-125°E)", 
                                         min_value=100.0, max_value=125.0, 
                                         value=(100.0, 125.0), step=0.5)
    
    # Filter data
    filtered_df = df[df['Ensemble'].isin(selected_ensembles) & 
                    (df['Latitude'].between(lat_min, lat_max)) & 
                    (df['Longitude'].between(lon_min, lon_max))]
    
    if not filtered_df.empty:
        # Time Series Plot
        st.subheader("MSLP Time Series")
        sample_df = filtered_df.groupby(['Forecast_Datetime', 'Ensemble', 'Dataset'])['MSLP'].mean().reset_index()
        stats_df = filtered_df.groupby('Forecast_Datetime')['MSLP'].agg(['mean', 'median', lambda x: x.quantile(0.25), lambda x: x.quantile(0.75)]).reset_index()
        stats_df.columns = ['Forecast_Datetime', 'Mean', 'Median', '25th Percentile', '75th Percentile']
        
        fig_time = go.Figure()
        for _, row in sample_df[['Ensemble', 'Dataset']].drop_duplicates().iterrows():
            ensemble, dataset = row['Ensemble'], row['Dataset']
            ensemble_data = sample_df[(sample_df['Ensemble'] == ensemble) & (sample_df['Dataset'] == dataset)]
            fig_time.add_trace(go.Scatter(
                x=ensemble_data['Forecast_Datetime'],
                y=ensemble_data['MSLP'],
                mode='lines',
                name=f'{dataset} Ensemble {ensemble}',
                line=dict(dash='dash' if dataset == 'Gencast' else 'solid')
            ))
        
        if len(selected_stats) == 2:
            ordered_stats = sorted(selected_stats, key=lambda x: x if x != '25th Percentile' else 'z')
            for i, stat in enumerate(ordered_stats):
                if stat in stats_df.columns:
                    fig_time.add_trace(go.Scatter(
                        x=stats_df['Forecast_Datetime'],
                        y=stats_df[stat],
                        mode='lines',
                        name=stat,
                        line=dict(width=3, dash='solid' if stat in ['Mean', 'Median'] else 'dot'),
                        fill='tonexty' if i == 1 else None,
                        fillcolor='rgba(0, 100, 255, 0.2)'
                    ))
        elif len(selected_stats) == 1:
            stat = selected_stats[0]
            if stat in stats_df.columns:
                fig_time.add_trace(go.Scatter(
                    x=stats_df['Forecast_Datetime'],
                    y=stats_df[stat],
                    mode='lines',
                    name=stat,
                    line=dict(width=3, dash='solid' if stat in ['Mean', 'Median'] else 'dot')
                ))
        
        fig_time.update_layout(
            title=f"MSLP Time Series (Date: {selected_date})",
            xaxis_title="Date",
            yaxis_title="MSLP (Pa)",
            showlegend=True,
            hovermode="x unified",
            template="plotly_white"
        )
        st.plotly_chart(fig_time, use_container_width=True)
        
        # Map Plot with Lines
        st.subheader("MSLP Time Series Map (South China Sea)")
        map_df = filtered_df.sort_values('Forecast_Datetime')
        
        fig_map = go.Figure()
        for _, row in map_df[['Ensemble', 'Dataset']].drop_duplicates().iterrows():
            ensemble, dataset = row['Ensemble'], row['Dataset']
            ensemble_data = map_df[(map_df['Ensemble'] == ensemble) & (map_df['Dataset'] == dataset)].sort_values('Forecast_Datetime')
            if len(ensemble_data['Forecast_Datetime'].unique()) > 1:
                fig_map.add_trace(go.Scattermapbox(
                    lat=ensemble_data['Latitude'],
                    lon=ensemble_data['Longitude'],
                    mode='lines',
                    name=f'{dataset} Ensemble {ensemble}',
                    line=dict(width=2, color='blue' if dataset == 'Gencast' else 'red'),
                    text=[f"MSLP: {mslp:.2f} Pa, Time: {dt}" for mslp, dt in zip(ensemble_data['MSLP'], ensemble_data['Forecast_Datetime'])],
                    hoverinfo='text+lat+lon'
                ))
            else:
                st.warning(f"No lines plotted for {dataset} Ensemble {ensemble} (only {len(ensemble_data['Forecast_Datetime'].unique())} timestamp available).")
        
        fig_map.update_layout(
            title=f"MSLP Time Series Map (Date: {selected_date}, Ensembles: {len(selected_ensembles)})",
            mapbox=dict(
                style="open-street-map",
                center=dict(lat=12.5, lon=112.5),
                zoom=4,
                uirevision='static'
            ),
            showlegend=True,
            height=800
        )
        fig_map.update_geos(
            lataxis_range=[0, 25],
            lonaxis_range=[100, 125]
        )
        st.plotly_chart(fig_map, use_container_width=True)
    else:
        st.warning("No data available for the selected ensembles and lat/lon ranges.")
else:
    st.error(f"No matching CSV files found in GCS bucket for the selected date.")