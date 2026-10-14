'use strict';
async function refresh() {
  try {
    const response = await fetch('cgi-bin/status.cgi', {cache: 'no-store'});
    if (!response.ok) throw new Error('Status is unavailable (' + response.status + ')');
    const status = await response.json();
    for (const field of ['model', 'firmware', 'ip']) document.getElementById(field).textContent = status[field];
    document.getElementById('uptime').textContent = status.uptime_seconds + ' seconds';
    document.getElementById('memory').textContent = status.memory.available_kB + ' / ' + status.memory.total_kB + ' kB';
    for (const profile of ['main', 'sub']) {
      const link = document.getElementById(profile);
      link.textContent = status.streams[profile];
      link.href = status.streams[profile];
    }
    document.getElementById('error').textContent = '';
  } catch (error) {
    document.getElementById('error').textContent = error.message;
  }
}
refresh();
setInterval(refresh, 15000);
