"""
SENTIMENT & SURENESS ANALYZER (GEMINI-POWERED)
=============================================
This script reads the structured predictions and adds two new metrics:
1. Sentiment Score (1-10): How positive or negative the prediction is.
2. Sureness Score (1-10): How certain the commenter sounds.

SETUP:
- Ensure GEMINI_API_KEY is in your .env file.
- Requires 'structured_predictions.csv' from the prediction_analyzer.py script.
"""

import os
import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv
import json
import time

# Load credentials
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY not found in .env.")
else:
    genai.configure(api_key=GEMINI_API_KEY)

class SentimentSurityAnalyzer:
    def __init__(self, model_name="gemini-1.5-flash"):
        self.model = genai.GenerativeModel(model_name)

    def analyze_sentiment_and_surity(self, text):
        """
        Analyzes the original text for sentiment and sureness.
        """
        prompt = f"""
        Analyze the following Reddit prediction post for Sentiment and Sureness.
        
        Text: "{text}"
        
        Return a JSON object with these EXACT keys:
        - "sentiment_score": integer (1 for very negative, 10 for very positive)
        - "sureness_score": integer (1 for very unsure/guessing, 10 for absolutely certain)
        - "explanation": string (brief reasoning for the scores)

        ONLY return the JSON object.
        """
        
        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip().replace("```json", "").replace("```", "")
            return json.loads(response_text)
        except Exception as e:
            print(f"Error during AI analysis: {e}")
            return None

    def process_predictions(self, input_csv="structured_predictions.csv", output_csv="analyzed_predictions.csv"):
        """
        Adds sentiment and sureness columns to the predictions CSV.
        """
        if not os.path.exists(input_csv):
            print(f"Error: {input_csv} not found. Run prediction_analyzer.py first.")
            return

        df = pd.read_csv(input_csv)
        print(f"Analyzing sentiment and sureness for {len(df)} predictions...")
        
        sentiments = []
        sureness_scores = []
        explanations = []

        for index, row in df.iterrows():
            print(f"Analyzing prediction {index + 1}/{len(df)}...")
            
            # Using the full original text as requested
            text_to_analyze = row.get("Reddit_Text", "")
            result = self.analyze_sentiment_and_surity(text_to_analyze)
            
            if result:
                sentiments.append(result.get("sentiment_score", 5))
                sureness_scores.append(result.get("sureness_score", 5))
                explanations.append(result.get("explanation", ""))
            else:
                sentiments.append(None)
                sureness_scores.append(None)
                explanations.append("Analysis failed")
            
            # Rate limiting for free tier
            time.sleep(2)

        # Update and save
        df["AI_Sentiment_Score"] = sentiments
        df["AI_Sureness_Score"] = sureness_scores
        df["AI_Analysis_Note"] = explanations
        
        df.to_csv(output_csv, index=False)
        print(f"Analysis complete. Results saved to {output_csv}")

if __name__ == "__main__":
    analyzer = SentimentSurityAnalyzer()
    analyzer.process_predictions()
