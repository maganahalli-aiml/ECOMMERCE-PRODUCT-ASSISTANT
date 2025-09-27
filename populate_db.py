#!/usr/bin/env python3
"""
Script to populate AstraDB with product data
"""
import sys
from product_assistant.etl.data_ingestion import DataIngestion

def main():
    print("🚀 Starting data ingestion to populate AstraDB...")
    
    try:
        # Initialize the data ingestion pipeline
        ingestion = DataIngestion()
        
        print("📡 Running ingestion pipeline...")
        ingestion.run_pipeline()
        
        print("✅ Data successfully ingested to AstraDB!")
        print("🎉 The vector database is now populated with product data!")
        
    except FileNotFoundError as e:
        print(f"❌ Data file not found: {e}")
        print("💡 Make sure product_reviews.csv exists in the data/ directory")
        sys.exit(1)
        
    except Exception as e:
        print(f"❌ Ingestion failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()