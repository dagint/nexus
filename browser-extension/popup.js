const serverUrlInput = document.getElementById("serverUrl");
const saveJobBtn = document.getElementById("saveJob");
const openDashboardBtn = document.getElementById("openDashboard");
const statusEl = document.getElementById("status");

// Load saved server URL
chrome.storage.sync.get(["serverUrl"], (result) => {
  if (result.serverUrl) {
    serverUrlInput.value = result.serverUrl;
  }
});

// Save server URL on change
serverUrlInput.addEventListener("change", () => {
  const url = serverUrlInput.value.trim().replace(/\/+$/, "");
  serverUrlInput.value = url;
  chrome.storage.sync.set({ serverUrl: url });
});

function showStatus(message, type) {
  statusEl.textContent = message;
  statusEl.className = type;
}

function getServerUrl() {
  const url = serverUrlInput.value.trim().replace(/\/+$/, "");
  if (!url) {
    showStatus("Please enter your server URL first.", "error");
    return null;
  }
  return url;
}

// Save current job
saveJobBtn.addEventListener("click", async () => {
  const serverUrl = getServerUrl();
  if (!serverUrl) return;

  saveJobBtn.disabled = true;
  showStatus("Extracting job data...", "success");

  try {
    // Send message to content script to extract job data
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    let jobData;
    try {
      const response = await chrome.tabs.sendMessage(tab.id, { action: "extractJob" });
      jobData = response;
    } catch (err) {
      // Content script may not be injected on this page; try scripting API
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: extractJobFallback,
      });
      jobData = results[0]?.result;
    }

    if (!jobData || !jobData.title) {
      showStatus("Could not extract job data from this page.", "error");
      saveJobBtn.disabled = false;
      return;
    }

    // Add the source URL
    jobData.apply_url = jobData.apply_url || tab.url;

    showStatus("Saving to Nexus...", "success");

    const res = await fetch(`${serverUrl}/jobs/share`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(jobData),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `Server returned ${res.status}`);
    }

    const result = await res.json();
    showStatus("Job saved successfully!", "success");
  } catch (err) {
    showStatus(`Error: ${err.message}`, "error");
  } finally {
    saveJobBtn.disabled = false;
  }
});

// Open dashboard
openDashboardBtn.addEventListener("click", () => {
  const serverUrl = getServerUrl();
  if (!serverUrl) return;
  chrome.tabs.create({ url: `${serverUrl}/dashboard` });
});

// Fallback extraction when content script is not available
function extractJobFallback() {
  const getText = (selectors) => {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) {
        const text = el.innerText.trim();
        if (text) return text;
      }
    }
    return "";
  };

  return {
    title: getText(["h1", "[class*='title']", "[class*='Title']"]),
    company: getText([
      "[class*='company']", "[class*='Company']",
      "[class*='employer']", "[class*='Employer']",
    ]),
    location: getText([
      "[class*='location']", "[class*='Location']",
    ]),
    description: getText([
      "[class*='description']", "[class*='Description']",
      "#content", ".content", "article",
    ]),
    source: window.location.hostname,
  };
}
