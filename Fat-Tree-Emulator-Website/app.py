# app.py

import os
import subprocess
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from fat_tree import FatTree  # Ensure fat_tree.py is in the same directory or properly referenced

app = Flask(__name__)

# Directory to store generated topology HTML files
TOPOLOGY_DIR = os.path.join(os.getcwd(), 'generated_topologies')
os.makedirs(TOPOLOGY_DIR, exist_ok=True)

# Directory to store traceroute results
TRACEROUTE_DIR = os.path.join(os.getcwd(), 'traceroute_results')
os.makedirs(TRACEROUTE_DIR, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate_topology():
    try:
        k = int(request.form.get('k'))
        if k % 2 != 0 or k <= 0:
            return "Error: k must be a positive even integer.", 400
    except (ValueError, TypeError):
        return "Error: Invalid value for k.", 400

    # Generate the Fat Tree topology
    config_folder = "configs"
    fat_tree = FatTree(k, config_folder)
    # fat_tree.build_fat_tree()

    # The generate_topology_graph_plotly method saves the HTML file
    output_html_file = f"fat_tree_k{k}_topology.html"
    output_html_path = os.path.join(TOPOLOGY_DIR, output_html_file)
    fat_tree.generate_topology_graph_plotly()

    # Move the generated HTML to the topology directory
    generated_html = os.path.join(os.getcwd(), output_html_file)
    if os.path.exists(generated_html):
        os.rename(generated_html, output_html_path)
    else:
        return "Error: Topology HTML file not found.", 500

    return redirect(url_for('view_topology', filename=output_html_file))

@app.route('/topology/<filename>')
def view_topology(filename):
    return render_template('result.html', filename=filename)

@app.route('/topology_file/<filename>')
def topology_file(filename):
    return send_from_directory(TOPOLOGY_DIR, filename)

@app.route('/ping', methods=['POST'])
def ping():
    data = request.get_json()
    source = data.get('source')
    destination = data.get('destination')

    if not source or not destination:
        return jsonify({'error': 'Source and destination are required.'}), 400

    # Implement the ping logic here.
    # For demonstration, we'll use the system's ping command.
    # In a real scenario, you'd target the IPs from your Fat Tree topology.

    try:
        # Example: ping -c 3 destination
        result = subprocess.run(['ping', '-c', '3', destination],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                timeout=10)

        if result.returncode == 0:
            return jsonify({'output': result.stdout}), 200
        else:
            return jsonify({'output': result.stderr}), 400

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Ping command timed out.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/traceroute', methods=['POST'])
def traceroute():
    data = request.get_json()
    destination = data.get('destination')

    if not destination:
        return jsonify({'error': 'Destination is required.'}), 400

    # Implement the traceroute logic here.
    try:
        # Example: traceroute destination
        result = subprocess.run(['traceroute', destination],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                timeout=30)

        if result.returncode == 0:
            return jsonify({'output': result.stdout}), 200
        else:
            return jsonify({'output': result.stderr}), 400

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Traceroute command timed out.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
