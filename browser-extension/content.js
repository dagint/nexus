// Nexus Helper - Content Script
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

  // getHTML is an alias for getText — kept for semantic clarity in extractors
  const getHTML = getText;

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

  function extractDice() {
    return {
      title: getText([
        ".job-title",
        'h1[data-cy="jobTitle"]',
        "h1",
      ]),
      company: getText([
        ".employer-name",
        '[data-cy="companyNameLink"]',
        '[data-cy="employerName"]',
        ".topcard-alias a",
      ]),
      location: getText([
        ".location",
        '[data-cy="locationText"]',
        ".job-info .icon-map-pin + span",
      ]),
      description: getHTML([
        ".job-description",
        '[data-cy="jobDescription"]',
        "#jobDescription",
        "#jobdescSec",
      ]),
      source: "dice",
    };
  }

  function extractWellfound() {
    return {
      title: getText([
        "h1",
        '[data-test="JobTitle"]',
        ".listing-title",
      ]),
      company: getText([
        ".company-name",
        '[data-test="CompanyName"]',
        "h2 a",
        ".styles_component__company a",
      ]),
      location: getText([
        ".location",
        '[data-test="Location"]',
        ".styles_component__location",
      ]),
      description: getHTML([
        ".description",
        '[data-test="JobDescription"]',
        ".job-description",
        ".styles_description__content",
      ]),
      source: "wellfound",
    };
  }

  function extractRemoteOK() {
    return {
      title: getText([
        "h1",
        "h2.company_and_position .position",
        ".job-listing-header h2",
      ]),
      company: getText([
        "h3.companyLink a",
        "h2.company_and_position .company",
        ".company-name",
      ]),
      location: getText([
        ".location",
        ".job-listing-location",
      ]) || "Remote",
      description: getHTML([
        ".description",
        ".job_description",
        ".markdown",
      ]),
      source: "remoteok",
    };
  }

  function extractBuiltIn() {
    return {
      title: getText([
        "h1",
        '[data-id="job-title"]',
        ".job-title",
      ]),
      company: getText([
        ".company-name",
        '[data-id="company-name"]',
        ".job-company-name",
        ".company-header-name a",
      ]),
      location: getText([
        ".job-info-location",
        '[data-id="job-location"]',
        ".job-location",
      ]),
      description: getHTML([
        ".job-description",
        '[data-id="job-description"]',
        "#job-description",
      ]),
      source: "builtin",
    };
  }

  function extractSimplyHired() {
    return {
      title: getText([
        "h1",
        ".jobposting-title h2",
        '[data-testid="viewJobTitle"]',
      ]),
      company: getText([
        ".jobposting-company",
        '[data-testid="viewJobCompany"]',
        ".company-name",
      ]),
      location: getText([
        ".jobposting-location",
        '[data-testid="viewJobLocation"]',
        ".job-location",
      ]),
      description: getHTML([
        ".jobposting-description",
        '[data-testid="viewJobBody"]',
        ".ViewJob-description",
      ]),
      source: "simplyhired",
    };
  }

  function extractZipRecruiter() {
    return {
      title: getText([
        "h1.job_title",
        "h1",
        ".job_title",
        '[data-testid="job-title"]',
      ]),
      company: getText([
        ".hiring_company_text",
        ".company_name",
        '[data-testid="company-name"]',
        "a.t_company_name",
      ]),
      location: getText([
        ".location_text",
        ".job_location",
        '[data-testid="job-location"]',
      ]),
      description: getHTML([
        ".jobDescriptionSection",
        ".job_description",
        '[data-testid="job-description"]',
        "#job-desc",
      ]),
      source: "ziprecruiter",
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
    if (hostname.includes("dice.com")) return extractDice();
    if (hostname.includes("wellfound.com") || hostname.includes("angel.co")) return extractWellfound();
    if (hostname.includes("remoteok.com") || hostname.includes("remoteok.io")) return extractRemoteOK();
    if (hostname.includes("builtin.com")) return extractBuiltIn();
    if (hostname.includes("simplyhired.com")) return extractSimplyHired();
    if (hostname.includes("ziprecruiter.com")) return extractZipRecruiter();
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
    btn.textContent = "Save to Nexus";

    function resetBtn() {
      btn.textContent = "Save to Nexus";
      btn.style.background = "#75b798";
      btn.disabled = false;
    }

    btn.addEventListener("click", async () => {
      btn.textContent = "Saving...";
      btn.disabled = true;

      try {
        const result = await chrome.storage.sync.get(["serverUrl"]);
        const serverUrl = result.serverUrl;

        if (!serverUrl) {
          btn.textContent = "Set server URL in extension popup";
          setTimeout(resetBtn, 3000);
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
        setTimeout(resetBtn, 3000);
      } catch (err) {
        btn.textContent = "Error - try again";
        btn.style.background = "#dc3545";
        setTimeout(resetBtn, 3000);
      }
    });

    document.body.appendChild(btn);
  }

  // --- Auto-detect saved/applied jobs ---

  function normalizeKey(title, company) {
    return (title + "||" + company).toLowerCase().replace(/\s+/g, " ").trim();
  }

  function highlightSavedJobs() {
    chrome.storage.sync.get(["serverUrl", "apiToken"], async (result) => {
      const serverUrl = result.serverUrl;
      const apiToken = result.apiToken;
      if (!serverUrl || !apiToken) return;

      try {
        const res = await fetch(`${serverUrl}/api/extension/my-jobs`, {
          headers: { "X-API-Token": apiToken },
        });
        if (!res.ok) return;

        const data = await res.json();
        const appliedKeys = new Set((data.applied_keys || []).map(k => k.toLowerCase()));
        const bookmarkedKeys = new Set((data.bookmarked_keys || []).map(k => k.toLowerCase()));

        if (appliedKeys.size === 0 && bookmarkedKeys.size === 0) return;

        // Find job cards on listing pages
        let jobCards = [];

        if (hostname.includes("linkedin.com")) {
          jobCards = document.querySelectorAll(".job-card-container, .jobs-search-results__list-item, .scaffold-layout__list-item");
        } else if (hostname.includes("indeed.com")) {
          jobCards = document.querySelectorAll(".job_seen_beacon, .jobsearch-ResultsList .result, .cardOutline, [data-testid='slider_item']");
        } else {
          // Generic: look for common card patterns
          jobCards = document.querySelectorAll("[class*='job-card'], [class*='JobCard'], [class*='job_card'], [class*='jobCard']");
        }

        jobCards.forEach((card) => {
          const titleEl = card.querySelector("h3, h2, [class*='title'], [class*='Title']");
          const companyEl = card.querySelector("[class*='company'], [class*='Company'], [class*='employer']");
          if (!titleEl) return;

          const title = (titleEl.innerText || "").trim();
          const company = (companyEl?.innerText || "").trim();
          if (!title) return;

          // Check by matching against keys (job keys often contain title/company slugs)
          const keyNorm = normalizeKey(title, company);
          let matched = false;
          let matchType = "";

          for (const key of appliedKeys) {
            if (key.includes(title.toLowerCase().substring(0, 20)) ||
                keyNorm.includes(key.substring(0, 20))) {
              matched = true;
              matchType = "applied";
              break;
            }
          }
          if (!matched) {
            for (const key of bookmarkedKeys) {
              if (key.includes(title.toLowerCase().substring(0, 20)) ||
                  keyNorm.includes(key.substring(0, 20))) {
                matched = true;
                matchType = "bookmarked";
                break;
              }
            }
          }

          if (matched) {
            card.style.borderLeft = matchType === "applied"
              ? "4px solid #198754"
              : "4px solid #0d6efd";
            card.style.position = "relative";

            // Add badge
            const badge = document.createElement("span");
            badge.textContent = matchType === "applied" ? "Applied" : "Saved";
            badge.style.cssText = `
              position:absolute;top:4px;right:4px;
              background:${matchType === "applied" ? "#198754" : "#0d6efd"};
              color:white;font-size:10px;padding:2px 6px;border-radius:3px;
              font-weight:600;z-index:999;
            `;
            // Avoid duplicate badges
            if (!card.querySelector(".nexus-badge")) {
              badge.classList.add("nexus-badge");
              card.appendChild(badge);
            }
          }
        });
      } catch (err) {
        // Silently fail - auto-detect is best-effort
      }
    });
  }

  // Wait for page to be ready, then add button and highlight
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      createFloatingButton();
      setTimeout(highlightSavedJobs, 1500); // Wait for job cards to render
    });
  } else {
    createFloatingButton();
    setTimeout(highlightSavedJobs, 1500);
  }
})();
