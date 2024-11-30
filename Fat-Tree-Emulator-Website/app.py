# app.py

import eventlet
eventlet.monkey_patch()

import os
import subprocess
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from fat_tree import FatTree  # Ensure fat_tree.py is in the same directory or properly referenced
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your_secure_secret_key')  # Use environment variable for security
socketio = SocketIO(app, async_mode='eventlet')  # Ensure eventlet is installed

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Directory to store generated topology HTML files
TOPOLOGY_DIR = os.path.join(os.getcwd(), 'generated_topologies')
os.makedirs(TOPOLOGY_DIR, exist_ok=True)

# Dictionary to manage multiple FatTree instances
fat_tree_instances = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate_topology():
    try:
        k = int(request.form.get('k'))
        if k % 2 != 0 or k <= 0:
            logger.error("Invalid value for k: %s", k)
            return "Error: k must be a positive even integer.", 400
    except (ValueError, TypeError):
        logger.exception("Failed to parse 'k' from form data.")
        return "Error: Invalid value for k.", 400

    config_folder = f"configs/configs_k{k}"
    if not os.path.exists("configs"):
        os.makedirs("configs")
    if not os.path.exists(config_folder):
        os.makedirs(config_folder)

    filename = f"fat_tree_k{k}_topology.html"

    # Generate a unique session ID for this build process
    session_id = str(uuid.uuid4())
    logger.info("Starting build process with session_id: %s", session_id)

    def build_topology_task(k, config_folder, filename, session_id):
        try:
            # Initialize FatTree with a callback to emit messages to the specific room
            fat_tree = FatTree(
                k,
                config_folder,
                lambda msg, error=False: emit_message(message=msg, error=error, session_id=session_id)
            )
            fat_tree_instances[session_id] = fat_tree
            fat_tree.build_fat_tree()
            fat_tree.generate_topology_graph_plotly()

            # Move the generated HTML to the topology directory
            generated_html = f"fat_tree_k{k}_topology.html"
            generated_html_path = os.path.join(os.getcwd(), generated_html)
            output_html_path = os.path.join(TOPOLOGY_DIR, generated_html)
            if os.path.exists(generated_html_path):
                os.rename(generated_html_path, output_html_path)
                emit_message("Topology HTML file generated successfully.", session_id=session_id)
            else:
                emit_message("Error: Topology HTML file not found.", error=True, session_id=session_id)
                return

            # Emit completion event
            emit_message("Build complete!", complete=True, session_id=session_id)
        except Exception as e:
            logger.exception("Error during build process: %s", e)
            emit_message(f"Error during build: {str(e)}", error=True, session_id=session_id)

    def emit_message(message, error=False, complete=False, session_id=None):
        """Helper function to emit messages to the client in a specific room."""
        data = {'message': message}
        if error:
            data['error'] = True
        if complete:
            data['complete'] = True
        if session_id:
            # Emit to the specific room
            socketio.emit('build_status', data, room=session_id)
            logger.info("Emitted message to session_id %s: %s", session_id, data)
        else:
            # Emit to all clients (fallback)
            socketio.emit('build_status', data)
            logger.info("Emitted message to all clients: %s", data)

    # Start the build process in a background task
    socketio.start_background_task(target=build_topology_task, k=k, config_folder=config_folder, filename=filename, session_id=session_id)

    # Redirect to the loading screen with the unique session ID
    return redirect(url_for('loading_screen', filename=filename, session_id=session_id))

@app.route('/cleanup', methods=['POST'])
def cleanup():
    data = request.get_json()
    session_id = data.get('session_id')

    if not session_id or session_id not in fat_tree_instances:
        logger.error("Invalid or missing session ID for cleanup: %s", session_id)
        return jsonify({'error': 'Invalid or missing session ID.'}), 400

    fat_tree = fat_tree_instances.pop(session_id)
    try:
        fat_tree.cleanup()  # Assuming the cleanup method handles Docker and network cleanup
        logger.info("Cleaned up FatTree instance for session_id: %s", session_id)
        return jsonify({'success': True, 'message': 'Cleanup completed successfully.'})
    except Exception as e:
        logger.exception("Error during cleanup for session_id %s: %s", session_id, e)
        return jsonify({'success': False, 'message': f'Cleanup failed: {str(e)}'}), 500

@app.route('/loading/<filename>')
def loading_screen(filename):
    session_id = request.args.get('session_id')
    if not session_id:
        logger.error("No session_id provided in the loading_screen request.")
        return "Error: Missing session ID.", 400
    return render_template('loading.html', filename=filename, session_id=session_id)
    
@app.route('/topology/<filename>')
def view_topology(filename):
    session_id = request.args.get('session_id')
    if not session_id:
        logger.error("No session_id provided in the view_topology request.")
        return "Error: Missing session ID.", 400
    return render_template('result.html', filename=filename, session_id=session_id)

@app.route('/topology_file/<filename>')
def topology_file(filename):
    return send_from_directory(TOPOLOGY_DIR, filename)

# app.py
@app.route('/ping', methods=['POST'])
def ping():
    data = request.get_json()
    session_id = data.get('session_id')
    source = data.get('source')
    destination = data.get('destination')

    if not session_id or session_id not in fat_tree_instances:
        logger.error("Invalid or missing session ID for ping: %s", session_id)
        return jsonify({'error': 'Invalid or missing session ID.'}), 400

    if not source or not destination:
        logger.error("Missing source or destination for ping.")
        return jsonify({'error': 'Source and destination are required.'}), 400

    fat_tree = fat_tree_instances[session_id]
    result = fat_tree.ping(source, destination)
    return jsonify(result)

@app.route('/traceroute', methods=['POST'])
def traceroute():
    data = request.get_json()
    session_id = data.get('session_id')
    source = data.get('source')
    destination = data.get('destination')

    if not session_id or session_id not in fat_tree_instances:
        logger.error("Invalid or missing session ID for traceroute: %s", session_id)
        return jsonify({'error': 'Invalid or missing session ID.'}), 400

    if not source or not destination:
        logger.error("Missing source or destination for traceroute.")
        return jsonify({'error': 'Source and destination are required.'}), 400

    fat_tree = fat_tree_instances[session_id]
    result = fat_tree.traceroute(source, destination)
    return jsonify(result)

@app.route('/get_servers/<session_id>', methods=['GET'])
def get_servers(session_id):
    if not session_id or session_id not in fat_tree_instances:
        logger.error("Invalid or missing session ID for get_servers: %s", session_id)
        return jsonify({'error': 'Invalid or missing session ID.'}), 400

    fat_tree = fat_tree_instances[session_id]
    server_names = [server.name for pod in fat_tree.pods for server in pod.servers]
    return jsonify({'servers': server_names})

# Handle client connection and joining room
@socketio.on('join')
def handle_join(data):
    session_id = data.get('session_id')
    if session_id:
        join_room(session_id)
        emit('joined', {'message': f'Joined room {session_id}'})
        logger.info("Client joined room: %s", session_id)
    else:
        logger.error("Client attempted to join without a session_id.")

# Optionally handle client disconnect
@socketio.on('disconnect')
def handle_disconnect():
    logger.info("Client disconnected.")

if __name__ == '__main__':
    # Replace app.run() with socketio.run()
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
