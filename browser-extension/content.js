// Job Search Tool Helper - Content Script
// Extracts job information from supported job listing sites.

(function () {
  "use strict";

  const hostname = window.location.hostname;

  // --- Extraction helpers ---

  function getText(selectors) {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) {
        const text = el.innerText.trim();
        if (text) return text;
      }
    }
    return "";
  }

  function getHTML(selectors) {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) {
        const text = el.innerText.trim();
        if (text) return text;
      }
    }
    return "";
  }

  function getMeta(name) {
    const el =
      document.querySelector(`meta[property="${name}"]`) ||
      document.querySelector(`meta[name="${name}"]`);
    return el ? el.content.trim() : "";
  }

  // --- Site-specific extractors ---

  function extractLinkedIn() {
    return {
      title: getText([
        ".jobs-unified-top-card__job-title",
        ".top-card-layout__title",
        "h1",
      ]),
      company: getText([
        ".jobs-unified-top-card__company-name",
        ".topcard__org-name-link",
        ".top-card-layout__second-subline a",
      ]),
      location: getText([
        ".jobs-unified-top-card__bullet",
        ".topcard__flavor--bullet",
        ".top-card-layout__second-subline .topcard__flavor:last-child",
      ]),
      description: getHTML([
        ".jobs-description__content",
        ".jobs-description-content__text",
        ".description__text",
        ".show-more-less-html__markup",
      ]),
      source: "linkedin",
    };
  }

  function extractIndeed() {
    return {
      title: getText([
        ".jobsearch-JobInfoHeader-title",
        '[data-testid="jobsearch-JobInfoHeader-title"]',
        "h1",
      ]),
      company: getText([
        ".jobsearch-InlineCompanyRating-companyHeader",
        '[data-testid="inlineHeader-companyName"]',
        '[data-company-name="true"]',
      ]),
      location: getText([
        ".jobsearch-JobInfoHeader-subtitle .css-6z8o9s",
        '[data-testid="inlineHeader-companyLocation"]',
        '[data-testid="job-location"]',
      ]),
      description: getHTML([
        "#jobDescriptionText",
        ".jobsearch-jobDescriptionText",
      ]),
      source: "indeed",
    };
  }

  function extractGlassdoor() {
    return {
      title: getText([
        '[data-test="jobTitle"]',
        ".css-1vg6q84",
        "h1",
      ]),
      company: getText([
        '[data-test="employerName"]',
        ".css-87uc0g",
        ".e1tk4kwz1",
      ]),
      location: getText([
        '[data-test="location"]',
        ".css-56kyx5",
        ".e1tk4kwz5",
      ]),
      description: getHTML([
        ".jobDescriptionContent",
        '[data-test="jobDescription"]',
        ".desc",
      ]),
      source: "glassdoor",
    };
  }

  function extractGreenhouse() {
    return {
      title: getText(["h1.app-title", "h1"]),
      company: getText([
        ".company-name",
        'meta[property="og:site_name"]',
      ]) || getMeta("og:site_name"),
      location: getText([".location", ".body--metadata"]),
      description: getHTML([
        "#content",
        ".content",
        "#app_body",
      ]),
      source: "greenhouse",
    };
  }

  function extractLever() {
    return {
      title: getText([".posting-headline h2", "h1", "h2"]),
      company: getMeta("og:site_name") || getText([".main-header-logo img"]),
      location: getText([
        ".posting-categories .sort-by-time",
        ".posting-categories .location",
        ".location",
      ]),
      description: getHTML([
        ".posting-page .content",
        '[data-qa="job-description"]',
        ".section-wrapper",
      ]),
      source: "lever",
    };
  }

  function extractGeneric() {
    return {
      title: getText(["h1", "[class*='title']", "[class*='Title']"]),
      company: getText([
        "[class*='company']",
        "[class*='Company']",
        "[class*='employer']",
        "[class*='Employer']",
      ]) || getMeta("og:site_name"),
      location: getText([
        "[class*='location']",
        "[class*='Location']",
      ]),
      description: getHTML([
        "[class*='description']",
        "[class*='Description']",
        "#content",
        ".content",
        "article",
      ]),
      source: hostname,
    };
  }

  function extractJobData() {
    if (hostname.includes("linkedin.com")) return extractLinkedIn();
    if (hostname.includes("indeed.com")) return extractIndeed();
    if (hostname.includes("glassdoor.com")) return extractGlassdoor();
    if (hostname.includes("greenhouse.io")) return extractGreenhouse();
    if (hostname.includes("lever.co")) return extractLever();
    return extractGeneric();
  }

  // --- Listen for messages from popup ---

  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "extractJob") {
      const data = extractJobData();
      data.apply_url = window.location.href;
      sendResponse(data);
    }
    return true; // keep the message channel open for async
  });

  // --- Floating save button ---

  function createFloatingButton() {
    if (document.getElementById("jst-floating-save-btn")) return;

    const btn = document.createElement("button");
    btn.id = "jst-floating-save-btn";
    btn.textContent = "Save to Job Search Tool";
    btn.addEventListener("click", async () => {
      btn.textContent = "Saving...";
      btn.disabled = true;

      try {
        const result = await chrome.storage.sync.get(["serverUrl"]);
        const serverUrl = result.serverUrl;

        if (!serverUrl) {
          btn.textContent = "Set server URL in extension popup";
          setTimeout(() => {
            btn.textContent = "Save to Job Search Tool";
            btn.disabled = false;
          }, 3000);
          return;
        }

        const jobData = extractJobData();
        jobData.apply_url = window.location.href;

        const res = await fetch(`${serverUrl}/jobs/share`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(jobData),
        });

        if (!res.ok) throw new Error(`Server error ${res.status}`);

        btn.textContent = "Saved!";
        btn.style.background = "#63a382";
        setTimeout(() => {
          btn.textContent = "Save to Job Search Tool";
          btn.style.background = "#75b798";
          btn.disabled = false;
        }, 3000);
      } catch (err) {
        btn.textContent = "Error - try again";
        btn.style.background = "#dc3545";
        setTimeout(() => {
          btn.textContent = "Save to Job Search Tool";
          btn.style.background = "#75b798";
          btn.disabled = false;
        }, 3000);
      }
    });

    document.body.appendChild(btn);
  }

  // Wait for page to be ready, then add button
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createFloatingButton);
  } else {
    createFloatingButton();
  }
})();
