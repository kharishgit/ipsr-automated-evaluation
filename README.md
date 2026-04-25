# 📊 AI-Based Excel Assignment Grading System

## 🚀 Overview

This project automates the evaluation of student  assignments using AI.

It performs:

* 📂 Bulk extraction of student submissions (from Moodle downloads)
* 📄 File parsing (Excel, CSV, PDF, etc.)
* 🤖 AI-based grading using LLMs (via OpenRouter)
* 📊 Rule-based scoring + intelligent evaluation
* 📝 Automated feedback generation
* 📁 Final results stored in a CSV file

---

## 🧠 Key Features

### ✅ 1. Bulk File Extraction

* Extracts individual student files from Moodle download folders
* Cleans filenames and organizes them into a structured directory

### ✅ 2. Multi-format Support

Supports:

* `.xlsx`, `.xls`
* `.csv`
* `.pdf`
* `.txt`, `.json`

---

### ✅ 3. Intelligent Grading System

Hybrid evaluation:

* 🧮 Rule-based scoring (quick checks like totals, averages)
* 🤖 AI-based grading (deep evaluation using LLM)

---

### ✅ 4. Excel-Aware Evaluation

* Reads **multiple sheets**
* Converts structured data into **LLM-friendly format**
* Detects:

  * Summary sections
  * Calculated values
  * Insights

---

### ✅ 5. Smart Handling of Edge Cases

* Ignores temp files (`~$`)
* Handles empty / corrupted files
* Re-evaluates low scores automatically

---

## 📁 Project Structure

```
IPSR/
│
├── valuation.py          # Main grading pipeline
├── extract.py            # Bulk extraction from Moodle folders
├── prompt_builder.py     # Prompt engineering logic
├── rule_engine.py        # Rule-based scoring
├── config.py             # Configurations (API, paths)
├── rubric.json           # Evaluation criteria
│
├── Submissions/          # Raw Moodle downloads
├── final_files/          # Clean extracted student files
├── output/
│   └── grades.csv        # Final results
│
├── logs/                 # Execution logs
└── README.md
```

---

## ⚙️ Setup Instructions

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd IPSR
```

---

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

---

### 3. Install dependencies

```bash
pip install -r requirements.txt
```



---

### 4. Setup environment variables

Create `.env` file:

```env
DEEPSEEK_API_KEY=your_openrouter_key
```

---

## ▶️ How to Run

### Step 1: Extract student files

```bash
python3 extract.py
```

👉 Moves and renames files into `final_files/`

---

### Step 2: Run grading

```bash
python3 valuation.py
```

---

### Step 3: Check output

```
output/grades.csv
```

---

## 🧾 Example Output

```
Full name,Grade,Feedback comments
John_Doe,75,
Jane_Smith,45,Missing calculations and summary
```

---

## 🧠 How Grading Works

### 🔹 Rule-Based Checks

* Presence of totals
* Basic data validation
* Missing values

### 🔹 AI Evaluation

* Understanding of dataset
* Correctness of calculations
* Insights and summary quality

### 🔹 Re-evaluation

* If score < 60 → evaluated multiple times for fairness(We Can set the Threshold)

---

## ⚠️ Limitations

* Cannot directly detect Excel formulas (only values)
* Charts are not fully interpreted
* Heavily dependent on data visibility

---

## 🚀 Future Improvements

* Detect actual Excel formulas (SUM, IF, VLOOKUP)
* Add vision model for charts
* Build web dashboard for results
* Add confidence scoring
* Manual review system for edge cases

---

## 👨‍💻 Author

Harish K
AI / NLP Enthusiast

---

## ⭐ If you found this useful

Give it a star ⭐ and feel free to contribute!
