async function sendPostRequest(url, data) {
	if (data.cmd == 'kill_client' && !window.confirm('Disconnect this miner? It reconnects on its own unless you change its settings.')) return;
	if (data.cmd == 'empty_thread' && !window.confirm('Disconnect every miner on this thread? They reconnect on their own.')) return;
	data.csrf = '%s';
	var r = await fetch(url, {
		method: 'POST',
		headers: {
			'Content-Type':'application/json'
		},
		body: JSON.stringify(data)
	});
	if (r.ok) {
		document.dispatchEvent(new Event('datum:refresh'));
		return;
	}
	if (r.status == 401) {
		alert('This action requires admin access.');
	} else {
		alert('Error ' + r.status);
	}
}
