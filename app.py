from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from langchain.llms import OpenAI
import os
import requests
import re
import pandas as pd
import matplotlib.pyplot as plt
import PyPDF2

app = Flask(__name__)

# Securely load secrets from environment variables
SECRET = os.getenv("SECRET_KEY", "your secret")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable not set")

import json
import base64
import io
from werkzeug.utils import secure_filename

def download_file(url):
    """Downloads a file from a URL and saves it locally."""
    local_filename = secure_filename(url.split('/')[-1])
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return local_filename

def read_pdf(filepath):
    """Reads the text from a PDF file."""
    with open(filepath, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        text = ""
        for page in reader.pages:
            text += page.extract_text()
    return text

from restrictedpython import compile_restricted
from restrictedpython.Guards import safe_builtins

def run_python_code(code):
    """Executes a string of Python code in a sandboxed environment."""

    # Define the allowed global environment for the code
    allowed_globals = {
        "__builtins__": safe_builtins,
        "pd": pd,
        "plt": plt,
        "io": io,
        "base64": base64,
        # Add any other safe modules you want to allow
    }

    # Redirect stdout to a buffer to capture output
    buffer = io.StringIO()
    import sys
    original_stdout = sys.stdout
    sys.stdout = buffer

    try:
        # Compile the code in a restricted environment
        byte_code = compile_restricted(code, '<string>', 'exec')
        # Execute the compiled code
        exec(byte_code, allowed_globals)
    except Exception as e:
        return f"Error: {e}"
    finally:
        # Restore stdout
        sys.stdout = original_stdout

    return buffer.getvalue()


def parse_answer(answer_text):
    """
    Parses the LLM's string output into a boolean, number, or JSON object.
    """
    answer_text = answer_text.strip()
    # Try to parse as JSON
    try:
        return json.loads(answer_text)
    except json.JSONDecodeError:
        pass
    # Try to parse as boolean
    if answer_text.lower() == 'true':
        return True
    if answer_text.lower() == 'false':
        return False
    # Try to parse as a number (integer or float)
    try:
        return int(answer_text)
    except ValueError:
        try:
            return float(answer_text)
        except ValueError:
            pass
    # If all else fails, return the original string
    return answer_text

def process_data_and_get_answer(question, page_source):
    """
    This function implements a ReAct-style agent loop.
    """
    llm = OpenAI()

    tools = {
        "download_file": download_file,
        "read_pdf": read_pdf,
        "run_python_code": run_python_code,
    }

    prompt_template = """
    You are a resourceful AI assistant that can solve complex data-related quizzes.
    You have access to the following tools:
    - download_file(url): Downloads a file from a URL.
    - read_pdf(filepath): Reads the text from a PDF file.
    - run_python_code(code): Executes Python code for data analysis, manipulation, and visualization. You can use libraries like pandas, matplotlib, etc.

    Here is the content of the webpage:
    ---
    {page_source}
    ---
    Here is the question:
    ---
    {question}
    ---

    This is your thought process.
    {history}
    """

    history = ""
    max_turns = 10

    for _ in range(max_turns):
        prompt = prompt_template.format(page_source=page_source, question=question, history=history)
        response = llm.predict(prompt).strip()

        history += response

        action_match = re.search(r"Action: (.*?)\((.*?)\)", response)
        final_answer_match = re.search(r"Final Answer: (.*)", response)

        if action_match:
            tool_name = action_match.group(1).strip()
            tool_input = action_match.group(2).strip()

            if tool_name in tools:
                try:
                    # This is a simplified way to handle args. A real implementation would be more robust.
                    # It assumes the input is a single string argument.
                    tool_input = tool_input.strip('"\'')
                    result = tools[tool_name](tool_input)
                    history += f"\nObservation: {result}\n"
                except Exception as e:
                    history += f"\nObservation: Error executing tool {tool_name}: {e}\n"
            else:
                history += f"\nObservation: Unknown tool {tool_name}\n"

        elif final_answer_match:
            answer = final_answer_match.group(1).strip()
            return parse_answer(answer)

        else:
            # If the LLM doesn't produce a valid action or final answer,
            # we can add a generic observation to guide it.
            history += "\nObservation: Please specify a tool to use with 'Action: tool_name(input)' or provide the final answer with 'Final Answer: ...'.\n"

    return parse_answer("Agent failed to find an answer within the turn limit.")

def solve_quiz(email, secret, url):
    try:
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        driver = webdriver.Chrome(options=options)
        driver.get(url)

        # Extract the question and page source
        question = driver.find_element(By.ID, 'result').text
        page_source = driver.page_source

        # Get the answer
        answer = process_data_and_get_answer(question, page_source)

        # Extract submission URL from the page
        page_text = driver.find_element(By.TAG_NAME, 'body').text
        submission_url_match = re.search(r'Post your answer to (https?://[^\s]+)', page_text)
        if not submission_url_match:
            driver.quit()
            return {"error": "Could not find submission URL"}

        submission_url = submission_url_match.group(1)

        driver.quit()

        # Submit the answer
        submission_payload = {
            "email": email,
            "secret": secret,
            "url": url,
            "answer": answer
        }
        response = requests.post(submission_url, json=submission_payload)
        response.raise_for_status()
        submission_response = response.json()

        print(f"Submission response: {submission_response}")

        # Handle new URL if provided
        if submission_response.get('correct') and submission_response.get('url'):
            return solve_quiz(email, secret, submission_response['url'])

        return submission_response

    except Exception as e:
        print(f"An error occurred: {e}")
        return {"error": str(e)}

@app.route('/', methods=['POST'])
def handle_quiz():
    if not request.is_json:
        return jsonify({"error": "Invalid JSON"}), 400

    data = request.get_json()
    email = data.get('email')
    secret = data.get('secret')
    url = data.get('url')

    if not all([email, secret, url]):
        return jsonify({"error": "Missing required fields"}), 400

    if secret != SECRET:
        return jsonify({"error": "Invalid secret"}), 403

    result = solve_quiz(email, secret, url)

    if "error" in result:
        return jsonify(result), 500

    return jsonify(result), 200

if __name__ == '__main__':
    app.run(debug=True)
