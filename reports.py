"""Local GhostNet reports. Nothing is uploaded."""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from core import UTC


def _protect(value):
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def export_ghostnet(journal, path, tagged_only=True):
    fields = ['id', 'received_utc', 'event_utc', 'source', 'frequency', 'mode', 'kind',
              'sender', 'destination', 'snr', 'classification', 'state', 'text']
    path = Path(path)
    with journal.lock, path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        sql = '''SELECT m.*, c.state AS state, c.classification AS conversation_classification, c.text AS conversation_text
                 FROM conversations c JOIN messages m ON m.id=c.first_id'''
        if tagged_only:
            sql += " WHERE c.classification != 'Unclassified traffic'"
        sql += ' ORDER BY c.last_id'
        for row in journal.db.execute(sql):
            values = dict(row)
            values['classification'] = values.pop('conversation_classification', values.get('classification'))
            values['text'] = values.pop('conversation_text', values.get('text'))
            writer.writerow({key: _protect(values.get(key)) for key in fields})
    return path


def heard_report(journal, metrics, path, plan=None):
    from dataclasses import asdict, is_dataclass
    import os
    import tempfile
    def plain(value):
        if is_dataclass(value): return plain(asdict(value))
        if isinstance(value, datetime): return value.isoformat()
        if isinstance(value, dict): return {k: plain(v) for k,v in value.items()}
        if isinstance(value, (list,tuple)): return [plain(v) for v in value]
        return value
    path = Path(path)
    with journal.lock:
        end = metrics.get('end_message_id', journal.db.execute('SELECT COALESCE(MAX(id),0) FROM messages').fetchone()[0])
        start = metrics.get('start_message_id', end)
        prefix = metrics.get('source_prefix')
        if prefix:
            messages = [dict(r) for r in journal.db.execute('SELECT * FROM messages WHERE id>? AND id<=? AND source LIKE ?', (start,end,prefix+'%'))]
        else:
            messages = [dict(r) for r in journal.db.execute('SELECT * FROM messages WHERE id>? AND id<=?', (start,end))]
        exists = journal.db.execute("SELECT 1 FROM sqlite_master WHERE name='conversations'").fetchone()
        if exists and prefix:
            conversations = [dict(r) for r in journal.db.execute('SELECT c.* FROM conversations c JOIN messages m ON m.id=c.first_id WHERE c.first_id>? AND c.last_id<=? AND m.source LIKE ? ORDER BY c.last_id', (start,end,prefix+'%'))]
        else:
            conversations = [dict(r) for r in journal.db.execute('SELECT * FROM conversations WHERE first_id>? AND last_id<=? ORDER BY last_id', (start,end))] if exists else []
    complete = [r for r in conversations if r['state'] in ('Complete frame','Checksum verified','Complete · no message checksum')]
    tagged = [r for r in complete if r['classification'] != 'Unclassified traffic']
    report = plain({
        'generated_utc': datetime.now(UTC), 'plan': plan or {}, 'metrics': dict(metrics),
        'audio_seconds': round(float(metrics.get('audio_seconds',0)),1),
        'decoded_frames': metrics.get('decoded_frames',0), 'session_raw_rows': len(messages),
        'tagged_messages': len(tagged), 'flash_messages': sum(r['classification']=='FLASH' for r in tagged),
        'incomplete_conversations': len(conversations)-len(complete),
        'raw_tagged_frames': sum(r['classification']!='Unclassified traffic' for r in messages),
        'heard': bool(tagged), 'tagged_texts': [r['text'] for r in tagged][-50:],
        'note': 'Only complete tagged JS8 conversations from this session count as heard. Tags do not authenticate a sender; RTTY remains preview.'
    })
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='report-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(report,stream,indent=2,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return report


def write_sha256(file_path, catalog_path):
    digest = hashlib.file_digest(Path(file_path).open('rb'), 'sha256').hexdigest()
    line = f'{digest}  {Path(file_path).name}\n'
    Path(catalog_path).write_text(line, encoding='utf-8')
    return digest
