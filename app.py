from flask import Flask, render_template, jsonify, request
import sqlite3
import json
from datetime import datetime, timedelta
import threading
import time
import random
from collections import defaultdict

app = Flask(__name__)

# Sample database setup
def init_db():
    conn = sqlite3.connect('ppe_monitoring.db')
    c = conn.cursor()
    
    # Create tables if they don't exist
    c.execute('''CREATE TABLE IF NOT EXISTS workers
                 (id INTEGER PRIMARY KEY, name TEXT, department TEXT, position TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS ppe_detections
                 (id INTEGER PRIMARY KEY, 
                  worker_id INTEGER,
                  timestamp DATETIME,
                  helmet INTEGER,
                  vest INTEGER,
                  gloves INTEGER,
                  goggles INTEGER,
                  boots INTEGER,
                  mask INTEGER,
                  confidence REAL,
                  camera_location TEXT,
                  FOREIGN KEY(worker_id) REFERENCES workers(id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS alerts
                 (id INTEGER PRIMARY KEY,
                  worker_id INTEGER,
                  timestamp DATETIME,
                  violation_type TEXT,
                  severity TEXT,
                  resolved INTEGER DEFAULT 0,
                  description TEXT)''')
    
    # Insert sample workers
    workers = [
        (1, 'John Smith', 'Construction', 'Foreman'),
        (2, 'Maria Garcia', 'Construction', 'Worker'),
        (3, 'David Chen', 'Manufacturing', 'Operator'),
        (4, 'Sarah Johnson', 'Warehouse', 'Supervisor'),
        (5, 'Mike Brown', 'Manufacturing', 'Technician')
    ]
    
    c.executemany('INSERT OR IGNORE INTO workers VALUES (?,?,?,?)', workers)
    conn.commit()
    conn.close()

# Initialize database
init_db()

class PPEAnalyzer:
    def __init__(self):
        self.violation_threshold = 3  # Number of consecutive violations before alert
        
    def analyze_ppe_compliance(self, detection_data):
        """Analyze PPE compliance and return compliance status"""
        required_ppe = ['helmet', 'vest', 'gloves']
        optional_ppe = ['goggles', 'boots', 'mask']
        
        compliance = {
            'required_missing': [],
            'optional_missing': [],
            'compliance_score': 100,
            'status': 'Compliant'
        }
        
        # Check required PPE
        for ppe in required_ppe:
            if not detection_data.get(ppe, 0):
                compliance['required_missing'].append(ppe)
        
        # Check optional PPE
        for ppe in optional_ppe:
            if not detection_data.get(ppe, 0):
                compliance['optional_missing'].append(ppe)
        
        # Calculate compliance score
        required_score = (1 - len(compliance['required_missing']) / len(required_ppe)) * 70
        optional_score = (1 - len(compliance['optional_missing']) / len(optional_ppe)) * 30
        compliance['compliance_score'] = round(required_score + optional_score, 1)
        
        # Determine status
        if compliance['required_missing']:
            compliance['status'] = 'Non-Compliant'
        elif compliance['compliance_score'] < 80:
            compliance['status'] = 'Partially Compliant'
        
        return compliance

ppe_analyzer = PPEAnalyzer()

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/dashboard_stats')
def dashboard_stats():
    """Get overall dashboard statistics"""
    conn = sqlite3.connect('ppe_monitoring.db')
    c = conn.cursor()
    
    # Get total workers
    c.execute('SELECT COUNT(*) FROM workers')
    total_workers = c.fetchone()[0]
    
    # Get today's detections
    today = datetime.now().date()
    c.execute('''SELECT COUNT(*), 
                        AVG(helmet), AVG(vest), AVG(gloves), AVG(goggles), AVG(boots), AVG(mask)
                 FROM ppe_detections 
                 WHERE DATE(timestamp) = ?''', (today,))
    result = c.fetchone()
    
    today_detections = result[0] if result[0] else 0
    avg_ppe = {
        'helmet': round((result[1] or 0) * 100, 1),
        'vest': round((result[2] or 0) * 100, 1),
        'gloves': round((result[3] or 0) * 100, 1),
        'goggles': round((result[4] or 0) * 100, 1),
        'boots': round((result[5] or 0) * 100, 1),
        'mask': round((result[6] or 0) * 100, 1)
    }
    
    # Get active alerts
    c.execute('SELECT COUNT(*) FROM alerts WHERE resolved = 0')
    active_alerts = c.fetchone()[0]
    
    # Calculate overall compliance rate
    c.execute('''SELECT COUNT(*) FROM ppe_detections 
                 WHERE helmet = 1 AND vest = 1 AND gloves = 1''')
    compliant_detections = c.fetchone()[0]
    
    overall_compliance = round((compliant_detections / today_detections * 100), 1) if today_detections > 0 else 0
    
    conn.close()
    
    return jsonify({
        'total_workers': total_workers,
        'today_detections': today_detections,
        'active_alerts': active_alerts,
        'overall_compliance': overall_compliance,
        'avg_ppe_usage': avg_ppe
    })

@app.route('/api/recent_detections')
def recent_detections():
    """Get recent PPE detections"""
    conn = sqlite3.connect('ppe_monitoring.db')
    c = conn.cursor()
    
    c.execute('''SELECT p.*, w.name, w.department 
                 FROM ppe_detections p 
                 JOIN workers w ON p.worker_id = w.id 
                 ORDER BY p.timestamp DESC LIMIT 20''')
    
    detections = []
    for row in c.fetchall():
        detection = {
            'id': row[0],
            'worker_name': row[11],
            'department': row[12],
            'timestamp': row[2],
            'helmet': bool(row[3]),
            'vest': bool(row[4]),
            'gloves': bool(row[5]),
            'goggles': bool(row[6]),
            'boots': bool(row[7]),
            'mask': bool(row[8]),
            'confidence': row[9],
            'camera_location': row[10]
        }
        
        # Analyze compliance
        compliance = ppe_analyzer.analyze_ppe_compliance(detection)
        detection.update(compliance)
        
        detections.append(detection)
    
    conn.close()
    return jsonify(detections)

@app.route('/api/worker_compliance')
def worker_compliance():
    """Get compliance data for all workers"""
    conn = sqlite3.connect('ppe_monitoring.db')
    c = conn.cursor()
    
    c.execute('''SELECT w.id, w.name, w.department, w.position,
                 COUNT(p.id) as total_detections,
                 AVG(CASE WHEN p.helmet = 1 THEN 1 ELSE 0 END) as helmet_rate,
                 AVG(CASE WHEN p.vest = 1 THEN 1 ELSE 0 END) as vest_rate,
                 AVG(CASE WHEN p.gloves = 1 THEN 1 ELSE 0 END) as gloves_rate
                 FROM workers w
                 LEFT JOIN ppe_detections p ON w.id = p.worker_id
                 GROUP BY w.id, w.name, w.department, w.position''')
    
    workers = []
    for row in c.fetchall():
        worker = {
            'id': row[0],
            'name': row[1],
            'department': row[2],
            'position': row[3],
            'total_detections': row[4] or 0,
            'helmet_rate': round((row[5] or 0) * 100, 1),
            'vest_rate': round((row[6] or 0) * 100, 1),
            'gloves_rate': round((row[7] or 0) * 100, 1),
            'compliance_score': round(((row[5] or 0) + (row[6] or 0) + (row[7] or 0)) / 3 * 100, 1)
        }
        workers.append(worker)
    
    conn.close()
    return jsonify(workers)

@app.route('/api/alerts')
def get_alerts():
    """Get active alerts"""
    conn = sqlite3.connect('ppe_monitoring.db')
    c = conn.cursor()
    
    c.execute('''SELECT a.*, w.name 
                 FROM alerts a 
                 JOIN workers w ON a.worker_id = w.id 
                 WHERE a.resolved = 0 
                 ORDER BY a.timestamp DESC''')
    
    alerts = []
    for row in c.fetchall():
        alert = {
            'id': row[0],
            'worker_name': row[7],
            'timestamp': row[2],
            'violation_type': row[3],
            'severity': row[4],
            'description': row[6]
        }
        alerts.append(alert)
    
    conn.close()
    return jsonify(alerts)

@app.route('/api/resolve_alert/<int:alert_id>', methods=['POST'])
def resolve_alert(alert_id):
    """Mark an alert as resolved"""
    conn = sqlite3.connect('ppe_monitoring.db')
    c = conn.cursor()
    
    c.execute('UPDATE alerts SET resolved = 1 WHERE id = ?', (alert_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/compliance_trends')
def compliance_trends():
    """Get compliance trends for the last 7 days"""
    conn = sqlite3.connect('ppe_monitoring.db')
    c = conn.cursor()
    
    trends = []
    for i in range(6, -1, -1):
        date = (datetime.now() - timedelta(days=i)).date()
        
        c.execute('''SELECT COUNT(*),
                            AVG(CASE WHEN helmet = 1 AND vest = 1 AND gloves = 1 THEN 1 ELSE 0 END)
                     FROM ppe_detections 
                     WHERE DATE(timestamp) = ?''', (date,))
        
        result = c.fetchone()
        total = result[0] or 0
        compliance_rate = round((result[1] or 0) * 100, 1) if total > 0 else 0
        
        trends.append({
            'date': date.strftime('%Y-%m-%d'),
            'compliance_rate': compliance_rate,
            'total_detections': total
        })
    
    conn.close()
    return jsonify(trends)

# Background thread to simulate real-time PPE detections
def generate_sample_data():
    """Generate sample PPE detection data for demonstration"""
    while True:
        conn = sqlite3.connect('ppe_monitoring.db')
        c = conn.cursor()
        
        # Random worker
        worker_id = random.randint(1, 5)
        
        # Generate random PPE detection (with occasional violations)
        detection = {
            'worker_id': worker_id,
            'timestamp': datetime.now().isoformat(),
            'helmet': random.choices([1, 0], weights=[0.85, 0.15])[0],
            'vest': random.choices([1, 0], weights=[0.90, 0.10])[0],
            'gloves': random.choices([1, 0], weights=[0.80, 0.20])[0],
            'goggles': random.choices([1, 0], weights=[0.60, 0.40])[0],
            'boots': random.choices([1, 0], weights=[0.75, 0.25])[0],
            'mask': random.choices([1, 0], weights=[0.50, 0.50])[0],
            'confidence': round(random.uniform(0.7, 0.99), 2),
            'camera_location': random.choice(['Gate A', 'Gate B', 'Workshop', 'Storage Area'])
        }
        
        c.execute('''INSERT INTO ppe_detections 
                    (worker_id, timestamp, helmet, vest, gloves, goggles, boots, mask, confidence, camera_location)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (detection['worker_id'], detection['timestamp'], detection['helmet'], 
                  detection['vest'], detection['gloves'], detection['goggles'], 
                  detection['boots'], detection['mask'], detection['confidence'], 
                  detection['camera_location']))
        
        # Check for violations and create alerts
        if not detection['helmet'] or not detection['vest'] or not detection['gloves']:
            violation_type = []
            if not detection['helmet']:
                violation_type.append('No Helmet')
            if not detection['vest']:
                violation_type.append('No Safety Vest')
            if not detection['gloves']:
                violation_type.append('No Gloves')
            
            severity = 'High' if not detection['helmet'] else 'Medium'
            
            c.execute('''INSERT INTO alerts 
                        (worker_id, timestamp, violation_type, severity, description)
                        VALUES (?, ?, ?, ?, ?)''',
                     (worker_id, detection['timestamp'], ', '.join(violation_type), 
                      severity, f'PPE violation detected at {detection["camera_location"]}'))
        
        conn.commit()
        conn.close()
        
        time.sleep(10)  # Add new detection every 10 seconds

# Start background thread for sample data
data_thread = threading.Thread(target=generate_sample_data, daemon=True)
data_thread.start()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)