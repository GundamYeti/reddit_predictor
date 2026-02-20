import praw
import pandas as pd
from datetime import datetime
import sys

# --- REDDIT API CREDENTIALS (PLACEHOLDERS) ---
CLIENT_ID = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"
USER_AGENT = "python:reddit_scraper:v1.0 (by /u/YOUR_USERNAME)"

def scrape_reddit(subreddit_name="dataengineering", limit=100):
    """
    Scrapes the top 'limit' hot posts from a specific subreddit and saves to CSV.
    """
    try:
        # Initialize PRAW
        reddit = praw.Reddit(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            user_agent=USER_AGENT
        )

        print(f"Connecting to r/{subreddit_name}...")
        subreddit = reddit.subreddit(subreddit_name)
        
        posts_data = []

        # Fetch hot posts
        for submission in subreddit.hot(limit=limit):
            try:
                # Basic error handling for missing fields
                post_info = {
                    "Title": getattr(submission, "title", "N/A"),
                    "Author": str(getattr(submission, "author", "N/A")),
                    "Score": getattr(submission, "score", 0),
                    "Num_Comments": getattr(submission, "num_comments", 0),
                    "URL": getattr(submission, "url", "N/A"),
                    "Creation_Date": datetime.fromtimestamp(submission.created_utc).strftime('%Y-%m-%d %H:%M:%S') if hasattr(submission, 'created_utc') else "N/A"
                }
                posts_data.append(post_info)
            except Exception as e:
                print(f"Error processing post {getattr(submission, 'id', 'unknown')}: {e}")

        # Convert to DataFrame
        df = pd.DataFrame(posts_data)

        if not df.empty:
            # Save to CSV
            output_file = "reddit_data.csv"
            df.to_csv(output_file, index=False)
            print(f"Successfully scraped {len(df)} posts and saved to {output_file}")
            return df
        else:
            print("No data found or extracted.")
            return None

    except Exception as e:
        print(f"A critical error occurred while connecting to Reddit: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # You can change the subreddit here
    scrape_reddit(subreddit_name="dataengineering", limit=100)
