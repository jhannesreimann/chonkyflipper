"""
Loot file manager: list, download, and delete captured files so they can be
retrieved from the dashboard instead of over SSH.
"""

import os
from flask import Blueprint, request, send_from_directory
from config import CAPTURES_DIR, SIGNALS_IR, SIGNALS_SUBGHZ, CARDS_DIR
from utils import api_success, api_error

bp = Blueprint('loot', __name__)

# Whitelisted categories -> (label, absolute directory). Only these dirs are
# ever served, and filenames are reduced to their basename, so there is no way
# to reach arbitrary paths on the filesystem.
LOOT_CATEGORIES = {
    'pcap': ('Packet Captures', CAPTURES_DIR),
    'ir': ('IR Signals', SIGNALS_IR),
    'subghz': ('Sub-GHz Signals', SIGNALS_SUBGHZ),
    'nfc': ('NFC Cards', CARDS_DIR),
}


def _category_dir(category):
    entry = LOOT_CATEGORIES.get(category)
    return entry[1] if entry else None


def _list_dir(category, label, directory):
    files = []
    try:
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            st = os.stat(path)
            files.append({
                'category': category,
                'category_label': label,
                'name': name,
                'size': st.st_size,
                'modified': st.st_mtime,
            })
    except FileNotFoundError:
        pass
    return files


@bp.route('/api/loot', methods=['GET'])
def loot_list():
    items = []
    for category, (label, directory) in LOOT_CATEGORIES.items():
        items.extend(_list_dir(category, label, directory))
    items.sort(key=lambda f: f['modified'], reverse=True)
    return api_success({'files': items, 'count': len(items)})


@bp.route('/api/loot/download', methods=['GET'])
def loot_download():
    directory = _category_dir(request.args.get('category'))
    name = request.args.get('name')
    if directory is None or not name:
        return api_error('invalid category or name', 400)
    safe_name = os.path.basename(name)
    if not os.path.isfile(os.path.join(directory, safe_name)):
        return api_error('file not found', 404)
    return send_from_directory(directory, safe_name, as_attachment=True)


@bp.route('/api/loot', methods=['DELETE'])
def loot_delete():
    directory = _category_dir(request.args.get('category'))
    name = request.args.get('name')
    if directory is None or not name:
        return api_error('invalid category or name', 400)
    safe_name = os.path.basename(name)
    path = os.path.join(directory, safe_name)
    if not os.path.isfile(path):
        return api_error('file not found', 404)
    try:
        os.remove(path)
        return api_success({'deleted': safe_name})
    except Exception as e:
        return api_error(str(e), 500)
