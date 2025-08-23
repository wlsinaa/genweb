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
st.title("MSLP Analysis: Time Series and South China Sea Map")

# Initialize GCS client
client = storage.Client()
bucket_name = "walter-weather-2"
prefix = "gencast_mslp/"

@st.cache_data
def list_csv_files():
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

# List available CSV files
csv_files = list_csv_files()

if csv_files:
    # Sidebar for filtering
    st.sidebar.header("Filter Options")
    
    # Date selection
    date_options = [date for _, date in csv_files]
    selected_date = st.sidebar.selectbox("Select Date", options=date_options)
    selected_file = next(file for file, date in csv_files if date == selected_date)
    
    # Sample selection
    df = load_data(selected_file)
    if df is not None:
        all_samples = sorted(df['Sample'].unique())
        selected_samples = st.sidebar.multiselect("Select Samples", options=all_samples, default=all_samples)
        
        # Statistics selection
        stat_options = ["Mean", "Median", "25th Percentile", "75th Percentile"]
        selected_stats = st.sidebar.multiselect("Select Statistics to Plot", options=stat_options, default=[])
        
        # Latitude and Longitude filters for map
        st.sidebar.subheader("Map Filters (South China Sea)")
        lat_min, lat_max = st.sidebar.slider("Latitude Range (0-25°N)", 
                                             min_value=0.0, max_value=25.0, 
                                             value=(0.0, 25.0), step=0.5)
        lon_min, lon_max = st.sidebar.slider("Longitude Range (100-125°E)", 
                                             min_value=100.0, max_value=125.0, 
                                             value=(100.0, 125.0), step=0.5)
        
        # Convert Datetime to datetime object
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        
        # Calculate forecast datetime based on Time_Step
        def calculate_forecast_time(row):
            base_time = row['Datetime']
            hours_offset = row['Time_Step'] * 12
            return base_time + timedelta(hours=hours_offset)
        
        df['Forecast_Datetime'] = df.apply(calculate_forecast_time, axis=1)
        
        # Filter data by samples and lat/lon
        filtered_df = df[df['Sample'].isin(selected_samples) & 
                        (df['Latitude'].between(lat_min, lat_max)) & 
                        (df['Longitude'].between(lon_min, lon_max))]
        
        if not filtered_df.empty:
            # Time Series Plot
            st.subheader("MSLP Time Series")
            sample_df = filtered_df.groupby(['Forecast_Datetime', 'Sample'])['MSLP'].mean().reset_index()
            stats_df = filtered_df.groupby('Forecast_Datetime')['MSLP'].agg(['mean', 'median', lambda x: x.quantile(0.25), lambda x: x.quantile(0.75)]).reset_index()
            stats_df.columns = ['Forecast_Datetime', 'Mean', 'Median', '25th Percentile', '75th Percentile']
            
            fig_time = go.Figure()
            for sample in selected_samples:
                sample_data = sample_df[sample_df['Sample'] == sample]
                fig_time.add_trace(go.Scatter(
                    x=sample_data['Forecast_Datetime'],
                    y=sample_data['MSLP'],
                    mode='lines',
                    name=f'Sample {sample}',
                    line=dict(dash='dash')
                ))
            for stat in selected_stats:
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
                hovermode="x unified"
            )
            st.plotly_chart(fig_time, use_container_width=True)
            
            # Map Plot with Lines
            st.subheader("MSLP Time Series Map (South China Sea)")
            # Aggregate MSLP by lat/lon, sample, and forecast datetime
            map_df = filtered_df.groupby(['Latitude', 'Longitude', 'Sample', 'Forecast_Datetime'])['MSLP'].mean().reset_index()
            
            # Create Mapbox figure
            fig_map = go.Figure()
            
            # Add lines for each sample at each lat/lon
            for sample in selected_samples:
                sample_data = map_df[map_df['Sample'] == sample]
                # Group by lat/lon to plot lines for each coordinate
                for (lat, lon) in sample_data[['Latitude', 'Longitude']].drop_duplicates().values:
                    coord_data = sample_data[(sample_data['Latitude'] == lat) & (sample_data['Longitude'] == lon)]
                    fig_map.add_trace(go.Scattermapbox(
                        lat=coord_data['Latitude'],
                        lon=coord_data['Longitude'],
                        mode='lines+markers',
                        name=f'Sample {sample} (Lat: {lat}, Lon: {lon})',
                        line=dict(width=2),
                        marker=dict(size=8, color=coord_data['MSLP'], colorscale='Viridis', showscale=True),
                        text=coord_data['MSLP'].round(2),
                        hoverinfo='text+lat+lon'
                    ))
            
            fig_map.update_layout(
                title=f"MSLP Time Series Map (Date: {selected_date}, Samples: {len(selected_samples)})",
                mapbox=dict(
                    style="open-street-map",  # Modern Mapbox style
                    center=dict(lat=12.5, lon=112.5),  # Center of South China Sea
                    zoom=4,  # Adjust for larger view
                    uirevision='static'  # Preserve zoom/pan state
                ),
                showlegend=True,
                height=800  # Larger map
            )
            fig_map.update_geos(
                lataxis_range=[0, 25],  # South China Sea: 0-25°N
                lonaxis_range=[100, 125]  # 100-125°E
            )
            st.plotly_chart(fig_map, use_container_width=True)
        else:
            st.warning("No data available for the selected samples and lat/lon ranges.")
    else:
        st.error("Failed to load data for the selected date. Check GCS bucket permissions or file path.")
else:
    st.error("No matching CSV files found in GCS bucket. Check bucket and file path.")