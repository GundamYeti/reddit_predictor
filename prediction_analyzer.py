"""
PREDICTION ANALYZER (GEMINI-POWERED)
====================================
This script uses Google's Gemini AI to analyze raw Reddit data and extract
verifiable predictions into a structured format.

SETUP INSTRUCTIONS:
1. Get a Gemini API Key: 
   Visit https://aistudio.google.com/app/apikey and click "Create API key".
2. Add your key to the .env file:
   GEMINI_API_KEY=your_key_here
3. Run this script:
   python prediction_analyzer.py
"""

import os
import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv
import json
import time

# Load credentials from .env
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("-" * 50)
    print("CRITICAL ERROR: GEMINI_API_KEY NOT FOUND")
    print("Please visit https://aistudio.google.com/app/apikey to get a key.")
    print("Then add it to your .env file as: GEMINI_API_KEY=your_key")
    print("-" * 50)
else:
    # Initialize the Gemini AI model
    genai.configure(api_key=GEMINI_API_KEY)

class PredictionAnalyzer:
    def __init__(self, model_name="gemini-1.5-flash"):
        self.model = genai.GenerativeModel(model_name)

    def get_structured_prediction(self, text):
        """
        Uses Gemini to determine if a text contains a prediction and extracts fields.
        """
        prompt = f"""
        Analyze the following text from Reddit and determine if it contains a verifiable prediction. 
        A prediction is a statement about a future event or outcome.
        
        Text: "{text}"
        
        Return a JSON object with these keys:
        - "is_prediction": boolean
        - "subject": string (what the prediction is about)
        - "outcome": string (the predicted result)
        - "deadline": string (the date or time frame, if mentioned)
        - "confidence": string (e.g., "high", "medium", "low" or "unknown")
        - "reasoning": string (short explanation)

        If it's NOT a prediction, set "is_prediction" to false and leave other fields null.
        ONLY return the JSON object.
        """
        
        try:
            response = self.model.generate_content(prompt)
            # Basic cleanup of response text in case of markdown formatting
            response_text = response.text.strip().replace("```json", "").replace("```", "")
            return json.loads(response_text)
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
            return None

    def process_csv(self, input_csv="reddit_data.csv", output_csv="structured_predictions.csv"):
        """
        Reads a CSV of Reddit posts, analyzes them, and saves structured predictions.
        """
        if not os.path.exists(input_csv):
            print(f"Error: {input_csv} not found. Please run the crawler first to generate data.")
            return

        df = pd.read_csv(input_csv)
        print(f"Analyzing {len(df)} posts for predictions...")
        
        predictions_list = []

        for index, row in df.iterrows():
            print(f"Processing post {index + 1}/{len(df)}...")
            
            # Combine Title and Text (if available) for better analysis
            text_to_analyze = row.get("Title", "")
            if "Text" in row and pd.notna(row["Text"]):
                text_to_analyze += " " + str(row["Text"])

            result = self.get_structured_prediction(text_to_analyze)
            
            if result and result.get("is_prediction"):
                # Combine original metadata with new structured fields
                prediction_entry = {
                    "Original_ID": row.get("ID", ""),
                    "Author": row.get("Author", ""),
                    "Reddit_Text": text_to_analyze,
                    "Subject": result.get("subject"),
                    "Predicted_Outcome": result.get("outcome"),
                    "Deadline": result.get("deadline"),
                    "Confidence": result.get("confidence"),
                    "Reasoning": result.get("reasoning"),
                    "Created_UTC": row.get("Creation_Date", "")
                }
                predictions_list.append(prediction_entry)
            
            # Simple rate-limit pause (Gemini Free Tier has limits)
            time.sleep(2)

        if predictions_list:
            results_df = pd.DataFrame(predictions_list)
            results_df.to_csv(output_csv, index=False)
            print(f"Successfully found {len(predictions_list)} predictions. Saved to {output_csv}")
        else:
            print("No verifiable predictions found in the current dataset.")

if __name__ == "__main__":
    analyzer = PredictionAnalyzer()
    # Assuming 'reddit_data.csv' exists from the crawler or scraper script
    analyzer.process_csv()
