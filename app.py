from flask import Flask, request, jsonify

app = Flask(__name__)

# This should be stored securely, e.g., in an environment variable
SECRET = "your secret"

@app.route('/', methods=['POST'])
def handle_quiz():
    # 1. Validate the request
    if not request.is_json:
        return jsonify({"error": "Invalid JSON"}), 400

    data = request.get_json()
    email = data.get('email')
    secret = data.get('secret')
    url = data.get('url')

    if not all([email, secret, url]):
        return jsonify({"error": "Missing required fields"}), 400

    # 2. Verify the secret
    if secret != SECRET:
        return jsonify({"error": "Invalid secret"}), 403

    # 3. Process the quiz (placeholder for now)
    # In the next steps, this is where we'll use the headless browser
    # to visit the URL and solve the quiz.
    print(f"Received quiz for {email} at {url}")

    # 4. Respond to the initial POST request
    return jsonify({"message": "Quiz received"}), 200

if __name__ == '__main__':
    app.run(debug=True)
