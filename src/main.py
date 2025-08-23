import streamlit as st
import pandas as pd
import plotly.express as px
from google.cloud import storage
from datetime import datetime, timedelta
import os

# Streamlit page configuration
st.set_page_config(page_title="Weather MSLP Time Series", layout="wide")

# Title
st.title("MSLP Time Series from GCS Bucket")

# Initialize GCS client
client = storage.Client()
bucket_name = "walter-weather-2"
file_path = "gencast_mslp/mslp_2023071312.csv"

@st.cache_data
def load_data():
    try:
        bucket = client.get_bucket(bucket_name)
        blob = bucket.blob(file_path)
        data = blob.download_as_string()
        df = pd.read_csv(pd.io.common.StringIO(data.decode('utf-8')))
        return df
    except Exception as e:
        st.error(f"Error loading data from GCS: {e}")
        return None

# Load data
df = load_data()

if df is not None:
    # Convert Datetime to datetime object
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    
    # Calculate forecast datetime based on Time_Step
    def calculate_forecast_time(row):
        base_time = row['Datetime']
        hours_offset = (int(row['Time_Step']) + 1) * 12  # Time_Step * 12 hours
        return base_time + timedelta(hours=hours_offset)
    
    df['Forecast_Datetime'] = df.apply(calculate_forecast_time, axis=1)
    
    # Sidebar for filtering
    st.sidebar.header("Filter Options")
    all_samples = sorted(df['Sample'].unique())
    selected_samples = st.sidebar.multiselect("Select Samples", options=all_samples, default=all_samples)
    
    # Filter data by samples
    filtered_df = df[df['Sample'].isin(selected_samples)]
    
    if not filtered_df.empty:
        # Aggregate MSLP across all lat/lon for each sample and time step (mean MSLP)
        agg_df = filtered_df.groupby(['Forecast_Datetime', 'Sample'])['MSLP'].mean().reset_index()
        
        # Plot time series for all selected samples in one graph
        fig = px.line(agg_df, x='Forecast_Datetime', y='MSLP', color='Sample',
                      title="MSLP Time Series (All Selected Samples, Aggregated Across Coordinates)",
                      labels={'Forecast_Datetime': 'Date', 'MSLP': 'Mean Sea Level Pressure (Pa)'})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No data available for the selected samples.")
else:
    st.error("Failed to load data. Check GCS bucket permissions or file path.")