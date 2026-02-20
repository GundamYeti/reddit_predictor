# 📉 Reddit Predictor: Historical Accuracy Tracker

An automated pipeline designed to crawl years of Reddit history, extract predictive statements, and verify their accuracy against real-world outcomes using the **Brier Score**.

---

## 🚀 Overview

The goal of this project is to quantify the "collective intelligence" (or lack thereof) of specific subreddits. By looking back at the last 5+ years of data, we can see who actually knew what they were talking about and who was just making noise.

### The Goal: The Brier Score
The system outputs a **Brier Score** ($BS = \frac{1}{N} \sum_{t=1}^{N} (f_t - o_t)^2$) for each subreddit, where:
- $f_t$ is the probability/confidence of the prediction.
- $o_t$ is the actual outcome (0 or 1).
- **Lower is better** (0.0 is a perfect oracle, 0.25 is a coin-flip).

---

## 🏗️ System Architecture

The project is divided into four modular phases:

### 1. 🔍 Historical Crawler (The "Time Machine")
Since the standard Reddit API limits us to the most recent 1,000 posts, this module uses a hybrid approach:
- **Pushshift Integration:** Accesses massive historical S3 dumps to pull comments and posts from 2018–Present.
- **Reddit API (PRAW):** Fetches metadata and updates for specific high-signal threads found during the historical sweep.

### 2. 🧠 Prediction Extractor (NLP Layer)
Not every comment is a prediction. This layer uses NLP (Natural Language Processing) to filter for:
- **Keywords:** "I bet", "will happen", "remindme!", "prediction".
- **Temporal Markers:** Dates, quarters (Q3 2024), or events (Election, Halving).
- **Confidence Extraction:** Determining if a user is "100% sure" or just "guessing."

### 3. ⚖️ Truth Verifier (The Judge)
This module connects to external "Ground Truth" APIs to verify if a prediction came true:
- **Finance:** Yahoo Finance / CoinGecko (for price targets).
- **Sports:** ESPN / Odds-API (for game outcomes).
- **General:** LLM-based web search (for political or cultural events).

### 4. 📊 Scorer & Visualizer
The final output is a **Calibration Plot**:
- **Line Graph:** Compares "Predicted Probability" vs. "Observed Frequency."
- **Brier Score Calculation:** A single number representing the subreddit's overall forecasting skill.
- **Leaderboard:** Ranks subreddits by their historical accuracy.

---

## 🛠️ Tech Stack

- **Language:** Python 3.9+
- **Data Handling:** `Pandas`, `NumPy`
- **APIs:** `PRAW` (Reddit), `Pushshift` (History)
- **Visualization:** `Matplotlib` / `Seaborn`
- **NLP:** `NLTK` / `Spacy`

---

## 🚦 Getting Started

1. **Clone the Repo:**
   ```bash
   git clone https://github.com/GundamYeti/reddit_predictor.git
   ```
2. **Setup Environment:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure API Keys:**
   Update the `.env` file with your Reddit `client_id` and `client_secret`.

---

## 📈 Roadmap
- [x] Initial Scraper Setup
- [x] GitHub Codespaces Configuration
- [ ] Integration with Pushshift for 5-year history
- [ ] Automated Brier Score Calculation
- [ ] Discord Webhook Alerts

---
*Created by GundamYeti*
