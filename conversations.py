"""Conservative, durable frame grouping. Missing/ambiguous frames stay incomplete."""
import json
from core import classify
from embedded import MODES

class Conversations:
    def __init__(self,journal):
        self.journal=journal
        with journal.lock,journal.db:
            journal.db.executescript('''
                CREATE TABLE IF NOT EXISTS conversations (
                  id INTEGER PRIMARY KEY, first_id INTEGER UNIQUE, last_id INTEGER,
                  state TEXT NOT NULL, text TEXT NOT NULL, classification TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversation_frames (
                  conversation_id INTEGER, frame_id INTEGER UNIQUE);
                CREATE INDEX IF NOT EXISTS conversation_frame_parent ON conversation_frames(conversation_id);
            ''')
            # Upgrade old journals without deleting the original records.
            journal.db.execute('''INSERT OR IGNORE INTO conversations(first_id,last_id,state,text,classification)
                SELECT id,id,'Legacy frame',text,classification FROM messages
                WHERE kind!='RX.ASSEMBLED' AND id NOT IN (SELECT frame_id FROM conversation_frames)''')
            journal.db.execute('''INSERT OR IGNORE INTO conversation_frames
                SELECT id,first_id FROM conversations''')

    def raw_id(self,packet,source):
        raw=json.dumps(packet,ensure_ascii=False,sort_keys=True)
        with self.journal.lock:
            row=self.journal.db.execute('SELECT id FROM messages WHERE source=? AND raw_json=? ORDER BY id DESC LIMIT 1',(source,raw)).fetchone()
            if row is None:
                raise LookupError('Decoded frame was not in the journal')
            return row[0]

    def create(self,frame_id,text,state,destination=''):
        with self.journal.lock,self.journal.db:
            cur=self.journal.db.execute('INSERT INTO conversations(first_id,last_id,state,text,classification) VALUES (?,?,?,?,?)',
                (frame_id,frame_id,state,text,classify(text,destination)))
            cid=cur.lastrowid
            self.journal.db.execute('INSERT INTO conversation_frames VALUES (?,?)',(cid,frame_id))
            return cid

    def update(self,cid,frame_id,text,state,destination=''):
        with self.journal.lock,self.journal.db:
            self.journal.db.execute('INSERT OR IGNORE INTO conversation_frames VALUES (?,?)',(cid,frame_id))
            classification=classify(text,destination)
            self.journal.db.execute('UPDATE conversations SET last_id=?,text=?,state=?,classification=? WHERE id=?',
                (frame_id,text,state,classification,cid))
            # Only frames proven to belong to this conversation inherit its tag.
            self.journal.db.execute('UPDATE messages SET classification=? WHERE id IN (SELECT frame_id FROM conversation_frames WHERE conversation_id=?)',
                (classification,cid))

    def rows(self,query='',tagged=False):
        sql='''SELECT m.*,c.id AS conversation_id,c.text AS conversation_text,c.state,c.classification AS conversation_classification
            FROM conversations c JOIN messages m ON m.id=c.first_id
            WHERE (instr(lower(c.text),lower(?))>0 OR instr(lower(m.sender),lower(?))>0)'''
        if tagged:sql+=" AND c.classification!='Unclassified traffic'"
        sql+=' ORDER BY c.last_id DESC LIMIT 500'
        with self.journal.lock:rows=[dict(r) for r in self.journal.db.execute(sql,(query,query))]
        for r in rows:
            r['text']=r.pop('conversation_text');r['classification']=r.pop('conversation_classification');r['id']=r['conversation_id']
        return rows

    def frames(self,cid):
        with self.journal.lock:
            return [dict(r) for r in self.journal.db.execute('SELECT m.* FROM messages m JOIN conversation_frames f ON f.frame_id=m.id WHERE f.conversation_id=? ORDER BY m.id',(cid,))]

class Assembler:
    def __init__(self,journal,validate):
        self.store=Conversations(journal)
        self.validate=validate
        self.pending={}

    def clear(self):
        self.pending.clear()

    def add(self,frame,raw_id,source,hz,epoch):
        mode=frame['mode'];period=MODES[mode]
        self.pending={k:p for k,p in self.pending.items() if epoch-p['last']<=MODES[p['mode']]*1.5}
        directed=frame.get('directed',[])
        sender=directed[0] if directed else frame.get('compound','')
        dest=directed[1] if len(directed)>1 else ''
        command=directed[2] if len(directed)>2 else ''
        if sender in ('<....>', '<...>', '...'):sender=''
        first=bool(frame['bits']&1);last=bool(frame['bits']&2)
        candidates=[p for p in self.pending.values() if p['source']==source and p['hz']==hz and p['mode']==mode
            and abs(p['offset']-frame['offset'])<=8 and period*.5<=epoch-p['last']<=period*1.5
            and (not sender or sender==p['sender'])]
        # Compound callsign followed by compound directed destination (type 2).
        # This is a header extension, not message data for checksum validation.
        header_candidates=[p for p in self.pending.values() if p.get('compound_header')
            and p['source']==source and p['hz']==hz and p['mode']==mode
            and abs(p['offset']-frame['offset'])<=8 and 0<=epoch-p['last']<=period*1.5
            and (not sender or sender==p['sender'])]
        if not first and frame['frame_type']==2 and dest and len(header_candidates)==1:
            p=header_candidates[0]
            p['dest']=dest;p['command']=command;p['last']=epoch
            p['header']+=frame['text'];p['text']=p['header'];p['body']=''
            p['compound_header']=False;p['low']=p['low'] or frame['low_confidence']
            state='Complete frame' if last else 'Incomplete'
            if p['low']:state='Low confidence · '+state
            self.store.update(p['cid'],raw_id,p['text'],state,dest)
            if last:
                self.pending.pop(p['cid'],None)
                if state=='Complete frame':
                    return {'id':p['cid'],'text':p['text'],'classification':classify(p['text'],dest)}
            return None
        # A new header never becomes data belonging to an earlier sender.
        continuation=not first and frame['frame_type'] in (4,6) and len(candidates)==1
        if continuation:
            p=candidates[0];p['body']+=frame['text'];p['text']+=frame['text'];p['last']=epoch
            p['low']=p['low'] or frame['low_confidence']
            state='Incomplete'
            if last:
                result=self.validate(p['command'],p['body'])
                state='Checksum failed' if not result['valid'] else ('Checksum verified' if result['checksum_bits'] else 'Complete · no message checksum')
                if result['valid']:p['text']=p['header']+result['text']
                if p.get('missing_header'):state='Incomplete · missing callsign header'
                if p['low']:state='Low confidence · '+state
                self.pending.pop(p['cid'],None)
            self.store.update(p['cid'],raw_id,p['text'],state,p['dest'])
            if last and state in ('Checksum verified','Complete · no message checksum'):
                return {'id':p['cid'],'text':p['text'],'classification':classify(p['text'],p['dest'])}
            return None
        state=('Complete frame' if first and last else 'Incomplete')
        if frame['low_confidence']:state='Low confidence · '+state
        cid=self.store.create(raw_id,frame['text'],state,dest)
        if not last and (first or (frame['frame_type']==2 and dest)):
            self.pending[cid]={'cid':cid,'mode':mode,'source':source,'hz':hz,'offset':frame['offset'],
                'sender':sender,'dest':dest,'command':command,'last':epoch,'text':frame['text'],
                'missing_header':not first,'compound_header':frame['frame_type']==1,
                'header':frame['text'] if directed or frame['frame_type']==1 else '', 'body':'' if directed or frame['frame_type']==1 else frame['text'],'low':frame['low_confidence']}
        if state=='Complete frame':return {'id':cid,'text':frame['text'],'classification':classify(frame['text'],dest)}
        return None
