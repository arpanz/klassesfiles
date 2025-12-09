let currentFile = null;
let currentData = null;

async function init() {
    const fileList = document.getElementById('fileList');
    
    try {
        // Fetch the list of files from files.json
        const response = await fetch('files.json');
        if (!response.ok) throw new Error('Failed to load file list');
        const files = await response.json();

        files.forEach(file => {
            const div = document.createElement('div');
            div.className = 'file-item';
            div.innerHTML = `
                <span class="file-name">${file}</span>
                <div class="actions">
                    <button class="btn-icon" onclick="event.stopPropagation(); downloadFile('${file}')" title="Download">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                    </button>
                </div>
            `;
            div.onclick = () => loadFile(file, div);
            fileList.appendChild(div);
        });
    } catch (error) {
        console.error(error);
        fileList.innerHTML = `<div style="padding: 1rem; color: #ef4444;">Error loading file list: ${error.message}</div>`;
    }
}

async function loadFile(filename, element) {
    // Update UI selection
    document.querySelectorAll('.file-item').forEach(el => el.classList.remove('active'));
    if(element) element.classList.add('active');

    try {
        const response = await fetch(filename);
        if (!response.ok) throw new Error('Failed to load file');
        
        const data = await response.json();
        currentFile = filename;
        currentData = data;
        
        displayData(filename, data);
    } catch (error) {
        console.error(error);
        document.getElementById('contentArea').innerHTML = `
            <div class="empty-state" style="color: #ef4444">
                <p>Error loading ${filename}</p>
                <small>${error.message}</small>
            </div>
        `;
    }
}

function displayData(filename, data) {
    document.getElementById('viewerHeader').style.display = 'flex';
    document.getElementById('currentFileName').textContent = filename;
    
    const contentArea = document.getElementById('contentArea');
    contentArea.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
}

function downloadFile(filename) {
    const a = document.createElement('a');
    a.href = filename;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

function downloadCurrentFile() {
    if (currentFile) {
        downloadFile(currentFile);
    }
}

// Initialize the app
init();