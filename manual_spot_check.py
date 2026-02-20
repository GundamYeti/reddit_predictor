"""
MANUAL SPOT-CHECK SCRIPT
========================
Allows a user to manually review predictions and the AI's analysis,
then provide their own ratings for "Truth", "Sentiment", and "Surity".
"""

import os
import pandas as pd
import json

def manual_spot_check(input_csv="analyzed_predictions.csv", output_csv="manual_reviews.csv"):
    """
    Displays each prediction and its AI scores, then prompts user for manual ratings.
    """
    if not os.path.exists(input_csv):
        print(f"Error: {input_csv} not found. Run sentiment_analyzer.py first.")
        return

    df = pd.read_csv(input_csv)
    print(f"Found {len(df)} predictions to review.")
    
    manual_reviews = []

    for index, row in df.iterrows():
        print("-" * 60)
        print(f"PREDICTION {index + 1} OF {len(df)}")
        print("-" * 60)
        print(f"POST BY: {row.get('Author')}")
        print(f"TEXT: {row.get('Reddit_Text')}")
        print("-" * 20)
        print(f"AI PREDICTED SUBJECT: {row.get('Subject')}")
        print(f"AI PREDICTED OUTCOME: {row.get('Predicted_Outcome')}")
        print(f"AI PREDICTED DEADLINE: {row.get('Deadline')}")
        print("-" * 20)
        print(f"AI SENTIMENT (1-10): {row.get('AI_Sentiment_Score')}")
        print(f"AI SURENESS  (1-10): {row.get('AI_Sureness_Score')}")
        print("-" * 20)
        
        # Collect manual ratings
        print("
--- YOUR REVIEW ---")
        try:
            truth = input("How TRUE did this turn out to be? (0=False, 1=True, p=Partial, skip=Skip): ")
            if truth.lower() == 'skip':
                continue
            
            sent = input("How positive/negative was it? (1=Very Neg, 10=Very Pos): ")
            sure = input("How sure did the user seem? (1=Very Unsure, 10=Very Sure): ")
            notes = input("Any additional notes/observations?: ")

            # Store review
            review = {
                "Original_ID": row.get("Original_ID"),
                "Reddit_Text": row.get("Reddit_Text"),
                "AI_Sentiment": row.get("AI_Sentiment_Score"),
                "AI_Sureness": row.get("AI_Sureness_Score"),
                "Manual_Truth": truth,
                "Manual_Sentiment": sent,
                "Manual_Sureness": sure,
                "Manual_Notes": notes
            }
            manual_reviews.append(review)
            
            # Save progress incrementally
            pd.DataFrame(manual_reviews).to_csv(output_csv, index=False)
            
            print(f"
Saved! Moving to next prediction...")
            
        except KeyboardInterrupt:
            print("
Exiting and saving current progress...")
            break

    print(f"
Manual spot check complete. All reviews saved to {output_csv}")

if __name__ == "__main__":
    manual_spot_check()
