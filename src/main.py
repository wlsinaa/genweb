import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from google.cloud import storage
from datetime import datetime, timedelta
import os
import re
from io import BytesIO
from PIL import Image

# Streamlit page configuration
st.set_page_config(page_title="Weather MSLP Analysis", layout="wide")

# Title
st.title("🌊 MSLP Analysis: Time Series and South China Sea Map")

# Define dataset prefixes
bucket_name = "walter-weather-2"
prefixes = ["gencast_mslp/", "gefs_mslp/", "ifs_mslp/"]
dataset_names = ["Gencast", "GEFS", "IFS"]

@st.cache_data
def list_csv_files(prefix):
    storage_client = storage.Client()
    try:
        blobs = storage_client.list_blobs(bucket_name, prefix=prefix)
        if prefix == "ifs_mslp/":
            pattern = r"mslp_data_\d{8}(12|00)\.csv$"
        else:
            pattern = r"mslp_\d{8}(12|00)\.csv$"
        csv_files = [blob.name for blob in blobs if re.match(pattern, blob.name.split('/')[-1])]
        dates = []
        for file in csv_files:
            date_str = file.split('/')[-1].replace('mslp_data_', '').replace('mslp_', '').replace('.csv', '')
            date = datetime.strptime(date_str, '%Y%m%d%H')
            dates.append((file, date.strftime('%Y-%m-%d %H:%M')))
        return sorted(dates, key=lambda x: x[1])
    except Exception as e:
        st.error(f"Error listing CSV files from GCS: {e}")
        return []

@st.cache_data
def load_data(file_path, dataset):
    storage_client = storage.Client()
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file_path)
        data = blob.download_as_text()
        df = pd.read_csv(pd.io.common.StringIO(data))
        df['Dataset'] = dataset
        if dataset == "Gencast":
            df['Ensemble'] = df['Sample']
            df['Forecast_Datetime'] = df.apply(
                lambda row: pd.to_datetime(row['Datetime']) + timedelta(hours=row['Time_Step'] * 12), axis=1)
            df['MSLP'] = df['MSLP'] / 100  # Convert to hPa
        elif dataset == "GEFS":
            df['Ensemble'] = df['Member']
            df['Forecast_Datetime'] = pd.to_datetime(df['Timestamp'])
        else:  # IFS
            df['Ensemble'] = 'IFS'  # IFS has no ensemble members
            df['Forecast_Datetime'] = pd.to_datetime(df['Datetime'])
            df['MSLP'] = df['Minimum_MSLP_hPa']  # Already in hPa
        # Standardize columns
        df = df[['Latitude', 'Longitude', 'MSLP', 'Forecast_Datetime', 'Ensemble', 'Dataset']]
        return df
    except Exception as e:
        st.error(f"Error loading data from GCS: {e}")
        return None

@st.cache_data
def list_png_files(prefix, base_time):
    storage_client = storage.Client()
    try:
        blobs = storage_client.list_blobs(bucket_name, prefix=prefix)
        date_str = base_time.replace(' ', '').replace(':', '').replace('-', '')
        patterns = [f"mslp_comparison_{date_str}.png", f"track_error_{date_str}.png"]
        png_files = {pattern: None for pattern in patterns}
        for blob in blobs:
            blob_name = blob.name.split('/')[-1]
            for pattern in patterns:
                if blob_name == pattern:
                    png_files[pattern] = blob.name
                    break  # Ensure at most one file per type
        return png_files
    except Exception as e:
        st.error(f"Error listing PNG files from gs://walter-weather-2/plots/: {e}")
        return {pattern: None for pattern in patterns}

@st.cache_data
def load_png(file_path):
    storage_client = storage.Client()
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file_path)
        data = blob.download_as_bytes()
        return Image.open(BytesIO(data))
    except Exception as e:
        st.error(f"Error loading PNG from gs://walter-weather-2/{file_path}: {e}")
        return None

# Sidebar for filtering
st.sidebar.header("Filter Options")

# Date selection
all_dates = set()
for prefix in prefixes:
    csv_files = list_csv_files(prefix)
    all_dates.update(date for _, date in csv_files)
date_options = sorted(list(all_dates))
selected_date = st.sidebar.selectbox("Select Date", options=date_options)

# Load data for selected date
dataframes = {name: None for name in dataset_names}
for prefix, dataset in zip(prefixes, dataset_names):
    pattern = r"mslp_data_\d{8}(12|00)\.csv$" if dataset == "IFS" else r"mslp_\d{8}(12|00)\.csv$"
    selected_file = next((file for file, date in list_csv_files(prefix) if date == selected_date), None)
    if selected_file:
        df = load_data(selected_file, dataset)
        if df is not None:
            dataframes[dataset] = df

# Combine datasets
valid_dfs = [dataframes[name] for name in dataset_names if dataframes[name] is not None]
df = pd.concat(valid_dfs, ignore_index=True) if valid_dfs else None

if df is not None:
    # Ensemble selection
    ensemble_options = {name: sorted(df[df['Dataset'] == name]['Ensemble'].unique()) if dataframes[name] is not None else [] for name in dataset_names}
    selected_ensembles = []
    for name in dataset_names:
        if ensemble_options[name]:
            selected = st.sidebar.multiselect(f"Select {name} Ensembles", options=ensemble_options[name], default=ensemble_options[name][:1] if name != "IFS" else ensemble_options[name])
            selected_ensembles.extend(selected)

    # Statistics selection
    stat_options = ["Mean", "Median", "10th Percentile", "25th Percentile", "75th Percentile", "90th Percentile"]
    selected_stats = st.sidebar.multiselect("Select Statistics to Plot (Max 2)",
                                           options=stat_options,
                                           default=[],
                                           max_selections=2)

    # Latitude and Longitude filters
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
        stats_df = filtered_df.groupby('Forecast_Datetime')['MSLP'].agg([
            'mean', 'median',
            lambda x: x.quantile(0.10), lambda x: x.quantile(0.25),
            lambda x: x.quantile(0.75), lambda x: x.quantile(0.90)
        ]).reset_index()
        stats_df.columns = ['Forecast_Datetime', 'Mean', 'Median', '10th Percentile', '25th Percentile', '75th Percentile', '90th Percentile']

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

# Display PNG Plots
st.subheader("MSLP Comparison and Track Error Plots")
date_str = selected_date.replace(' ', '').replace(':', '').replace('-', '')
png_files = list_png_files("plots/", selected_date)
for plot_type in [f"mslp_comparison_{date_str}.png", f"track_error_{date_str}.png"]:
    plot_name = "MSLP Comparison" if "mslp_comparison" in plot_type else "Track Error"
    st.write(f"**{plot_name} Plot**")
    file_path = png_files[plot_type]
    if file_path:
        image = load_png(file_path)
        if image:
            st.image(image, caption=f"{plot_name} for {selected_date} (gs://walter-weather-2/{file_path})", use_column_width=True)
        else:
            st.write("Cannot Extract")
    else:
        st.write("Cannot Extract")