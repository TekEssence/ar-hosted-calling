"""Synthetic live-LLM checks. No account writes, phone calls or real patient details."""
import json
import urllib.request

from prompts import compose_call_prompt

account = {'UID': 'synthetic-validation', 'Account Number': 'TEST-001',
           'Patient Name': 'Synthetic Patient', 'Billed Amount': '265',
           'AR Final Comments': 'Prior records show payment 21.22 and copay 80. Follow up for check encashed date, pay-to address and EOB.'}
with urllib.request.urlopen('http://127.0.0.1:8001/v1/models', timeout=15) as response:
    model = json.load(response)['data'][0]['id']
scenarios = [
    ('caller_role', 'Always ask if there is anything else you can help with.',
     'You have reached claims. How can I help you?'),
    ('payment_reconciliation', '',
     'The claim is fully adjudicated, with 21 dollars and 22 cents paid, an 80 dollar copay, and the rest a contractual adjustment.'),
    ('cleared_date', '', 'The check cleared on June 10, 2026.'),
]
for name, custom, utterance in scenarios:
    messages = [{'role': 'system', 'content': compose_call_prompt(account, custom)},
                {'role': 'assistant', 'content': 'Hello, this is an AR specialist calling regarding claim TEST-001. I am following up on this claim.'},
                {'role': 'user', 'content': utterance}]
    request = urllib.request.Request('http://127.0.0.1:8001/v1/chat/completions',
        data=json.dumps({'model': model, 'messages': messages, 'max_tokens': 220, 'temperature': 0}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=120) as response:
        reply = json.load(response)['choices'][0]['message']['content']
    print(f'{name}: {reply}', flush=True)
    lower = reply.lower()
    assert 'anything else i can help' not in lower and 'how can i help' not in lower, name
    assert reply.count('?') <= 1, name
    assert '[CALL_RESULT]' not in reply, name
    assert 'TEST-001' not in reply, name
    if name == 'caller_role':
        assert 'clear' in lower or 'cash' in lower, name
    if name == 'payment_reconciliation':
        assert 'denied' not in lower and 'denial code' not in lower, name
    if name == 'cleared_date':
        assert 'june' in lower and '2026' in lower and '?' in reply, name
print('Synthetic prompt behavior checks: OK')
