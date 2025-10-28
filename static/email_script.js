document.getElementById('create').addEventListener('click', async function(e){
  e.preventDefault();
  const payload = {
    name: 'campaign',
    recipients: document.getElementById('recipients').value,
    subjects: document.getElementById('subjects').value,
    body_plain: document.getElementById('body_plain').value,
    body_html: document.getElementById('body_html').value,
    html_template: document.getElementById('html_template').value,
    sender_name: document.getElementById('sender_name').value,
    sender_email: document.getElementById('sender_email').value
  };
  const res = await fetch('/create_campaign',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(res.ok) alert('Created'); else alert('Failed');
});
