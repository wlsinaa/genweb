import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from google.cloud import storage
from datetime import datetime, timedelta
import os
import re
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Streamlit page configuration
st.set_page_config(page_title="Weather MSLP Analysis", layout="wide")

# Title
st.title("🌊 MSLP Analysis: Time Series and South China Sea Map")

# Initialize GCS client
try:
    client = storage.Client()
except Exception as e:
    st.error(f"Failed to initialize GCS client: {e}")
    client = None

bucket_name = "walter-weather-2"
prefixes = ["gencast_mslp/", "gefs_mslp/", "ifs_mslp/"]

@st.cache_data
def list_csv_files(prefix):
    logger.debug(f"Listing files for prefix: {prefix}")
    try:
        bucket = client.get_bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=prefix)
        pattern = r"(mslp_\d{8}(12|00)\.csv|mslp_data_\d{8}(12|00)\.csv)$"
        csv_files = [blob.name for blob in blobs if re.match(pattern, blob.name.split('/')[-1])]
        logger.debug(f"Found files: {csv_files}")
        dates = []
        for file in csv_files:
            date_str = file.split('/')[-1].replace('mslp_', '').replace('mslp_data_', '').replace('.csv', '')
            try:
                date = datetime.strptime(date_str, '%Y%m%d%H')
                dates.append((file, date.strftime('%Y-%m-%d %H:%M')))
            except ValueError as e:
                logger.error(f"Failed to parse date from file {file}: {e}")
        return sorted(dates, key=lambda x: x[1])
    except Exception as e:
        st.error(f"Error listing files from GCS for prefix {prefix}: {e}")
        logger.error(f"Error listing files: {e}")
        return []

@st.cache_data
def load_data(file_path, dataset):
    logger.debug(f"Loading data from {file_path} for dataset {dataset}")
    try:
        bucket = client.get_bucket(bucket_name)
        blob = bucket.blob(file_path)
        data = blob.download_as_string()
        df = pd.read_csv(pd.io.common.StringIO(data.decode('utf-8')))
        logger.debug(f"Columns in {file_path}: {list(df.columns)}")
        
        # Validate required columns
        required_columns = ['Latitude', 'Longitude']
        if not all(col in df.columns for col in required_columns):
            st.error(f"Missing required columns in {file_path}: {required_columns}")
            logger.error(f"Missing columns in {file_path}: {required_columns}")
            return None
        
        df['Dataset'] = dataset
        if dataset == "Gencast":
            if 'Sample' not in df.columns or 'Datetime' not in df.columns or 'Time_Step' not in df.columns or 'MSLP' not in df.columns:
                st.error(f"Missing required columns for Gencast in {file_path}: ['Sample', 'Datetime', 'Time_Step', 'MSLP']")
                logger.error(f"Missing Gencast columns in {file_path}")
                return None
            df['Ensemble'] = df['Sample']
            df['Forecast_Datetime'] = df.apply(
                lambda row: pd.to_datetime(row['Datetime']) + timedelta(hours=row['Time_Step'] * 12), axis=1)
            df['MSLP'] = df['MSLP'] / 1000  # Convert to hPa
        elif dataset == "GEFS":
            if 'Member' not in df.columns or 'Timestamp' not in df.columns or 'MSLP' not in df.columns:
                st.error(f"Missing required columns for GEFS in {file_path}: ['Member', 'Timestamp', 'MSLP']")
                logger.error(f"Missing GEFS columns in {file_path}")
                return None
            df['Ensemble'] = df['Member']
            df['Forecast_Datetime'] = pd.to_datetime(df['Timestamp'])
            df['MSLP'] = df['MSLP']  # Assuming MSLP is in hPa
        else:  # IFS
            if 'Datetime' not in df.columns or 'Minimum_MSLP_hPa' not in df.columns:
                st.error(f"Missing required columns for IFS in {file_path}: ['Datetime', 'Minimum_MSLP_hPa']")
                logger.error(f"Missing IFS columns in {file_path}")
                return None
            df['Ensemble'] = "IFS"  # Deterministic model
            df['Forecast_Datetime'] = pd.to_datetime(df['Datetime'])
            df['MSLP'] = df['Minimum_MSLP_hPa']  # Already in hPa
        return df[['Dataset', 'Ensemble', 'Forecast_Datetime', 'MSLP', 'Latitude', 'Longitude']]
    except Exception as e:
        st.error(f"Error loading data from GCS for {file_path}: {e}")
        logger.error(f"Error loading data: {e}")
        return None

# Sidebar for filtering
st.sidebar.header("Filter Options")

# Date selection
all_dates = set()
for prefix in prefixes:
    dataset = prefix.split('_')[0].capitalize()
    csv_files = list_csv_files(prefix)
    logger.debug(f"Dates for {dataset}: {[date for _, date in csv_files]}")
    all_dates.update(date for _, date in csv_files)

date_options = sorted(list(all_dates))
selected_date = st.sidebar.selectbox("Select Date", options=date_options)

# Load data for all datasets
gencast_df = None
gefs_df = None
ifs_df = None
for prefix in prefixes:
    dataset = prefix.split('_')[0].capitalize()
    csv_files = list_csv_files(prefix)
    selected_file = next((file for file, date in csv_files if date == selected_date), None)
    if selected_file:
        df = load_data(selected_file, dataset)
        if df is not None:
            logger.debug(f"Loaded {dataset} data with {len(df)} rows")
            if dataset == "Gencast":
                gencast_df = df
            elif dataset == "GEFS":
                gefs_df = df
            else:  # IFS
                ifs_df = df

# Combine datasets
if gencast_df is not None and gefs_df is not None and ifs_df is not None:
    df = pd.concat([gencast_df, gefs_df, ifs_df], ignore_index=True)
elif gencast_df is not None and gefs_df is not None:
    df = pd.concat([gencast_df, gefs_df], ignore_index=True)
elif gencast_df is not None and ifs_df is not None:
    df = pd.concat([gencast_df, ifs_df], ignore_index=True)
elif gefs_df is not None and ifs_df is not None:
    df = pd.concat([gefs_df, ifs_df], ignore_index=True)
elif gencast_df is not None:
    df = gencast_df
elif gefs_df is not None:
    df = gefs_df
elif ifs_df is not None:
    df = ifs_df
else:
    df = None

if df is not None:
    logger.debug(f"Combined DataFrame has {len(df)} rows")
    # Separate ensemble selection for each dataset
    gencast_ensembles = sorted(gencast_df['Ensemble'].unique()) if gencast_df is not None else []
    gefs_ensembles = sorted(gefs_df['Ensemble'].unique()) if gefs_df is not None else []
    ifs_ensembles = sorted(ifs_df['Ensemble'].unique()) if ifs_df is not None else []
    
    st.sidebar.subheader("Ensemble Selection")
    selected_gencast = st.sidebar.multiselect("Select Gencast Ensembles", options=gencast_ensembles, default=[])
    selected_gefs = st.sidebar.multiselect("Select GEFS Ensembles", options=gefs_ensembles, default=[])
    selected_ifs = st.sidebar.multiselect("Select IFS Ensembles", options=ifs_ensembles, default=[])
    selected_ensembles = selected_gencast + selected_gefs + selected_ifs
    logger.debug(f"Selected ensembles: {selected_ensembles}")
    
    # Statistics selection for time series (max 2)
    stat_options = ["Mean", "Median", "25th Percentile", "75th Percentile"]
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
    logger.debug(f"Filtered DataFrame has {len(filtered_df)} rows")
    
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
                line=dict(dash='dash' if dataset == 'Gencast' else 'solid' if dataset == 'GEFS' else 'dot')
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
            yaxis_title="MSLP (hPa)",
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
                if 'Latitude' not in ensemble_data.columns or 'Longitude' not in ensemble_data.columns:
                    st.warning(f"Skipping map plot for {dataset} Ensemble {ensemble} (missing Latitude/Longitude).")
                    logger.warning(f"Missing Latitude/Longitude for {dataset} Ensemble {ensemble}")
                    continue
                fig_map.add_trace(go.Scattermapbox(
                    lat=ensemble_data['Latitude'],
                    lon=ensemble_data['Longitude'],
                    mode='lines',
                    name=f'{dataset} Ensemble {ensemble}',
                    line=dict(width=2, color='blue' if dataset == 'Gencast' else 'red' if dataset == 'GEFS' else 'green'),
                    text=[f"MSLP: {mslp:.2f} hPa, Time: {dt}" for mslp, dt in zip(ensemble_data['MSLP'], ensemble_data['Forecast_Datetime'])],
                    hoverinfo='text+lat+lon'
                ))
            else:
                st.warning(f"No lines plotted for {dataset} Ensemble {ensemble} (only {len(ensemble_data['Forecast_Datetime'].unique())} timestamp available).")
                logger.warning(f"Single timestamp for {dataset} Ensemble {ensemble}")
        
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
        logger.warning("Filtered DataFrame is empty")
else:
    st.error(f"No matching CSV files found in GCS bucket for the selected date.")
    logger.error("No data loaded for any dataset")