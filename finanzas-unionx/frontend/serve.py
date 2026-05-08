#!/usr/bin/env python3
"""
Simple HTTP Server para servir el dashboard HTML
Ejecutar: python serve.py
Acceder a: http://localhost:5173
"""
import http.server
import socketserver
import os
from pathlib import Path

PORT = 5173
FRONTEND_DIR = Path(__file__).parent

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def end_headers(self):
        # Allow CORS for localhost
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

def run_server():
    os.chdir(str(FRONTEND_DIR))

    with socketserver.TCPServer(("", PORT), MyHTTPRequestHandler) as httpd:
        print(f"[OK] Servidor corriendo en http://localhost:{PORT}")
        print(f"[DASHBOARD] Abre en tu navegador: http://localhost:{PORT}/dashboard.html")
        print(f"[INFO] Presiona Ctrl+C para detener")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[STOP] Servidor detenido")

if __name__ == '__main__':
    run_server()
