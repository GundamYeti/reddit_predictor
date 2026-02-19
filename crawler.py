import praw
import pandas as pd
import re
from datetime import datetime
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class RedditPredictorCrawler:
    def __init__(self):
        # Initialize PRAW with credentials from .env
        self.reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent=os.getenv("REDDIT_USER_AGENT", "python:prediction_tracker:v0.1 (by /u/your_username)")
        )
        
        # Regex patterns that might indicate a prediction
        self.prediction_patterns = [
            r"i predict that",
            r"will happen",
            r"going to happen",
            r"bet that",
            r"remindme!",
            r"price will be",
            r"by the end of",
            r"mark my words"
        ]

    def is_prediction(self, text):
        """Simple regex-based filter to identify potential predictions."""
        text = text.lower()
        for pattern in self.prediction_patterns:
            if re.search(pattern, text):
                return True
        return False

    def crawl_subreddit(self, subreddit_name, limit=100):
        """Crawls a subreddit for comments/posts that look like predictions."""
        print(f"Crawling r/{subreddit_name}...")
        subreddit = self.reddit.subreddit(subreddit_name)
        
        predictions = []

        # Look at submissions - note: API limits historical access
        # For true 5-year history, we might need to look into archive dumps (Pushshift)
        for submission in subreddit.new(limit=limit):
            if self.is_prediction(submission.title) or self.is_prediction(submission.selftext):
                predictions.append({
                    'type': 'submission',
                    'id': submission.id,
                    'author': str(submission.author),
                    'text': submission.title + " " + submission.selftext,
                    'created_utc': datetime.fromtimestamp(submission.created_utc),
                    'score': submission.score,
                    'url': submission.url
                })
                
            # Check comments
            submission.comments.replace_more(limit=0)
            for comment in submission.comments.list():
                if self.is_prediction(comment.body):
                    predictions.append({
                        'type': 'comment',
                        'id': comment.id,
                        'author': str(comment.author),
                        'text': comment.body,
                        'created_utc': datetime.fromtimestamp(comment.created_utc),
                        'score': comment.score,
                        'url': f"https://reddit.com{comment.permalink}"
                    })

        return pd.DataFrame(predictions)

if __name__ == "__main__":
    # Example usage
    crawler = RedditPredictorCrawler()
    
    # You will need to set up your .env file with REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET
    if not os.getenv("REDDIT_CLIENT_ID"):
        print("ERROR: Please set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in a .env file.")
    else:
        df = crawler.crawl_subreddit("wallstreetbets", limit=100)
        print(f"Found {len(df)} potential predictions.")
        if not df.empty:
            df.to_csv("predictions.csv", index=False)
            print("Saved to predictions.csv")
