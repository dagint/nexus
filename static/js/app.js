// Nexus - Client-side filtering and interactions

// CSRF-aware fetch wrapper
function csrfFetch(url, options) {
    options = options || {};
    options.headers = options.headers || {};
    var token = document.querySelector('meta[name="csrf-token"]');
    if (token) {
        options.headers["X-CSRFToken"] = token.getAttribute("content");
    }
    return fetch(url, options);
}

document.addEventListener("DOMContentLoaded", function () {
    // --- Theme toggle ---
    var themeToggle = document.getElementById("themeToggle");
    if (themeToggle) {
        var currentTheme = document.documentElement.getAttribute("data-bs-theme") || "light";
        themeToggle.textContent = currentTheme === "dark" ? "Light" : "Dark";

        themeToggle.addEventListener("click", function () {
            var newTheme = document.documentElement.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-bs-theme", newTheme);
            localStorage.setItem("theme", newTheme);
            themeToggle.textContent = newTheme === "dark" ? "Light" : "Dark";
        });
    }

    // --- Client-side filtering ---
    const filterChecks = document.querySelectorAll(".filter-check");
    const sourceChecks = document.querySelectorAll(".source-check");

    function applyFilters() {
        const cards = document.querySelectorAll(".job-card");
        const remoteOnly = document.getElementById("filterRemote")?.checked;
        const hideTravel = document.getElementById("filterHideTravel")?.checked;
        const hideStaffing = document.getElementById("filterHideStaffing")?.checked;
        const hideStale = document.getElementById("filterHideStale")?.checked;
        const hideApplied = document.getElementById("filterHideApplied")?.checked;
        const hideDismissed = document.getElementById("filterHideDismissed")?.checked;

        const activeSources = new Set();
        sourceChecks.forEach(function (cb) {
            if (cb.checked) activeSources.add(cb.dataset.source);
        });

        cards.forEach(function (card) {
            let show = true;

            if (remoteOnly && card.dataset.remote !== "remote") show = false;
            if (hideTravel && card.dataset.travel === "yes") show = false;
            if (hideStaffing && card.dataset.staffing === "yes") show = false;
            if (hideStale && card.dataset.stale === "yes") show = false;
            if (hideApplied && card.dataset.applied === "yes") show = false;
            if (hideDismissed && card.dataset.dismissed === "yes") show = false;
            if (!activeSources.has(card.dataset.source)) show = false;

            card.classList.toggle("hidden", !show);
        });
    }

    filterChecks.forEach(function (cb) {
        cb.addEventListener("change", applyFilters);
    });
    sourceChecks.forEach(function (cb) {
        cb.addEventListener("change", applyFilters);
    });

    // Apply initial filters
    applyFilters();

    // --- Mark as Applied ---
    document.querySelectorAll(".applied-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var jobKey = this.dataset.jobKey;
            var isApplied = this.dataset.applied === "true";

            if (isApplied) {
                csrfFetch("/jobs/" + jobKey + "/applied", { method: "DELETE" })
                    .then(function (resp) { if (!resp.ok) throw new Error("Failed"); })
                    .then(function () {
                        btn.textContent = "Mark Applied";
                        btn.classList.remove("btn-outline-secondary");
                        btn.classList.add("btn-outline-success");
                        btn.dataset.applied = "false";
                        btn.closest(".job-card").dataset.applied = "no";
                        applyFilters();
                    })
                    .catch(function () { btn.textContent = "Error - retry"; });
            } else {
                csrfFetch("/jobs/" + jobKey + "/applied", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        title: this.dataset.title || "",
                        company: this.dataset.company || "",
                    }),
                })
                    .then(function (resp) { if (!resp.ok) throw new Error("Failed"); })
                    .then(function () {
                        btn.textContent = "Applied";
                        btn.classList.remove("btn-outline-success");
                        btn.classList.add("btn-outline-secondary");
                        btn.dataset.applied = "true";
                        btn.closest(".job-card").dataset.applied = "yes";
                        applyFilters();
                    })
                    .catch(function () { btn.textContent = "Error - retry"; });
            }
        });
    });

    // --- Apply link tracking ---
    document.querySelectorAll(".apply-link").forEach(function (link) {
        link.addEventListener("click", function () {
            var jobKey = this.dataset.jobKey;
            csrfFetch("/jobs/" + jobKey + "/applied", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: this.dataset.title || "",
                    company: this.dataset.company || "",
                }),
            });
        });
    });

    // --- Bookmark toggle ---
    document.querySelectorAll(".bookmark-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var jobKey = this.dataset.jobKey;
            var isBookmarked = this.dataset.bookmarked === "true";

            if (isBookmarked) {
                csrfFetch("/jobs/" + jobKey + "/bookmark", { method: "DELETE" })
                    .then(function (resp) { if (!resp.ok) throw new Error("Failed"); })
                    .then(function () {
                        btn.textContent = "Bookmark";
                        btn.classList.remove("btn-warning");
                        btn.classList.add("btn-outline-warning");
                        btn.dataset.bookmarked = "false";
                    })
                    .catch(function () { btn.textContent = "Error - retry"; });
            } else {
                csrfFetch("/jobs/" + jobKey + "/bookmark", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        title: btn.dataset.title || "",
                        company: btn.dataset.company || "",
                    }),
                })
                    .then(function (resp) { if (!resp.ok) throw new Error("Failed"); })
                    .then(function () {
                        btn.textContent = "Bookmarked";
                        btn.classList.remove("btn-outline-warning");
                        btn.classList.add("btn-warning");
                        btn.dataset.bookmarked = "true";
                    })
                    .catch(function () { btn.textContent = "Error - retry"; });
            }
        });
    });

    // --- Dismiss toggle ---
    document.querySelectorAll(".dismiss-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var jobKey = this.dataset.jobKey;
            var isDismissed = this.dataset.dismissed === "true";

            if (isDismissed) {
                csrfFetch("/jobs/" + jobKey + "/dismiss", { method: "DELETE" })
                    .then(function (resp) { if (!resp.ok) throw new Error("Failed"); })
                    .then(function () {
                        btn.innerHTML = '<span aria-hidden="true">&darr;</span> Not Interested';
                        btn.classList.remove("btn-secondary");
                        btn.classList.add("btn-outline-secondary");
                        btn.dataset.dismissed = "false";
                        btn.closest(".job-card").dataset.dismissed = "no";
                        applyFilters();
                    })
                    .catch(function () { btn.textContent = "Error - retry"; });
            } else {
                csrfFetch("/jobs/" + jobKey + "/dismiss", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        title: this.dataset.title || "",
                        company: this.dataset.company || "",
                    }),
                })
                    .then(function (resp) { if (!resp.ok) throw new Error("Failed"); })
                    .then(function () {
                        btn.textContent = "Dismissed";
                        btn.classList.remove("btn-outline-secondary");
                        btn.classList.add("btn-secondary");
                        btn.dataset.dismissed = "true";
                        btn.closest(".job-card").dataset.dismissed = "yes";
                        applyFilters();
                    })
                    .catch(function () { btn.textContent = "Error - retry"; });
            }
        });
    });

    // --- Cover Letter Generation ---
    document.querySelectorAll(".cover-letter-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var title = this.dataset.title || "";
            var company = this.dataset.company || "";
            var description = this.dataset.description || "";
            var originalText = this.textContent;

            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Generating...';

            csrfFetch("/jobs/cover-letter", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: title,
                    company: company,
                    description: description,
                }),
            })
                .then(function (resp) {
                    return resp.json().then(function (data) {
                        return { ok: resp.ok, data: data };
                    });
                })
                .then(function (result) {
                    btn.disabled = false;
                    btn.textContent = originalText;

                    if (!result.ok) {
                        alert(result.data.error || "Failed to generate cover letter.");
                        return;
                    }

                    var contentEl = document.getElementById("coverLetterContent");
                    contentEl.textContent = result.data.cover_letter;

                    var modal = new bootstrap.Modal(document.getElementById("coverLetterModal"));
                    modal.show();
                })
                .catch(function (err) {
                    btn.disabled = false;
                    btn.textContent = originalText;
                    alert("Error generating cover letter: " + err.message);
                });
        });
    });

    // --- Copy Cover Letter to Clipboard ---
    var copyBtn = document.getElementById("copyCoverLetter");
    if (copyBtn) {
        copyBtn.addEventListener("click", function () {
            var text = document.getElementById("coverLetterContent").textContent;
            navigator.clipboard.writeText(text).then(function () {
                copyBtn.textContent = "Copied!";
                setTimeout(function () {
                    copyBtn.textContent = "Copy to Clipboard";
                }, 2000);
            }).catch(function () {
                // Fallback for older browsers
                var textarea = document.createElement("textarea");
                textarea.value = text;
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand("copy");
                document.body.removeChild(textarea);
                copyBtn.textContent = "Copied!";
                setTimeout(function () {
                    copyBtn.textContent = "Copy to Clipboard";
                }, 2000);
            });
        });
    }

    // --- Compare jobs ---
    var compareBar = document.getElementById("compareBar");
    var compareBtn = document.getElementById("compareBtn");
    var compareClear = document.getElementById("compareClear");
    var compareCount = document.getElementById("compareCount");

    function updateCompareBar() {
        if (!compareBar) return;
        var checked = document.querySelectorAll(".compare-check:checked");
        compareCount.textContent = checked.length;
        compareBar.classList.toggle("d-none", checked.length === 0);
        compareBtn.disabled = checked.length < 2 || checked.length > 4;
    }

    document.querySelectorAll(".compare-check").forEach(function(cb) {
        cb.addEventListener("change", function() {
            if (document.querySelectorAll(".compare-check:checked").length > 4) {
                this.checked = false;
            }
            updateCompareBar();
        });
    });

    if (compareBtn) {
        compareBtn.addEventListener("click", function() {
            var keys = [];
            document.querySelectorAll(".compare-check:checked").forEach(function(cb) {
                keys.push(cb.dataset.jobKey);
            });
            window.location.href = "/compare?keys=" + keys.join(",");
        });
    }

    if (compareClear) {
        compareClear.addEventListener("click", function() {
            document.querySelectorAll(".compare-check:checked").forEach(function(cb) {
                cb.checked = false;
            });
            updateCompareBar();
        });
    }

    // --- Share job ---
    document.querySelectorAll(".share-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var originalText = this.textContent;
            btn.disabled = true;
            btn.textContent = "Sharing...";

            csrfFetch("/jobs/share", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    job_key: this.dataset.jobKey || "",
                    title: this.dataset.title || "",
                    company: this.dataset.company || "",
                    location: this.dataset.location || "",
                    description: this.dataset.description || "",
                    apply_url: this.dataset.applyUrl || "",
                    remote_status: this.dataset.remoteStatus || "",
                    source: this.dataset.source || "",
                }),
            })
                .then(function (resp) { return resp.json(); })
                .then(function (data) {
                    btn.disabled = false;
                    if (data.share_url) {
                        navigator.clipboard.writeText(data.share_url).then(function () {
                            btn.textContent = "Link Copied!";
                            setTimeout(function () { btn.textContent = originalText; }, 2000);
                        }).catch(function () {
                            prompt("Share this link:", data.share_url);
                            btn.textContent = originalText;
                        });
                    } else {
                        btn.textContent = originalText;
                        alert(data.error || "Failed to create share link.");
                    }
                })
                .catch(function () {
                    btn.disabled = false;
                    btn.textContent = originalText;
                });
        });
    });

    // --- Notifications ---
    var notifBell = document.getElementById("notificationBell");
    var notifList = document.getElementById("notificationList");
    var markAllReadBtn = document.getElementById("markAllRead");

    if (notifBell) {
        notifBell.addEventListener("click", function () {
            csrfFetch("/notifications")
                .then(function (resp) { return resp.json(); })
                .then(function (data) {
                    if (!data.notifications || data.notifications.length === 0) {
                        notifList.innerHTML = '<span class="dropdown-item text-muted small">No new notifications</span>';
                        return;
                    }
                    var html = "";
                    data.notifications.forEach(function (n) {
                        var time = n.created_at ? n.created_at.substring(5, 16) : "";
                        if (n.link) {
                            html += '<a class="dropdown-item small" href="' + n.link + '">' + n.message + '<br><small class="text-muted">' + time + '</small></a>';
                        } else {
                            html += '<span class="dropdown-item small">' + n.message + '<br><small class="text-muted">' + time + '</small></span>';
                        }
                    });
                    notifList.innerHTML = html;
                });
        });
    }

    if (markAllReadBtn) {
        markAllReadBtn.addEventListener("click", function () {
            csrfFetch("/notifications/read", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({}),
            }).then(function () {
                notifList.innerHTML = '<span class="dropdown-item text-muted small">No new notifications</span>';
                var badge = document.querySelector("#notificationBell .badge");
                if (badge) badge.remove();
            });
        });
    }

    // --- Screening Questions ---
    var screeningJobData = {};
    document.querySelectorAll(".screening-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            screeningJobData = {
                title: this.dataset.title || "",
                company: this.dataset.company || "",
                description: this.dataset.description || "",
            };
            // Reset modal state
            document.getElementById("screeningInput").classList.remove("d-none");
            document.getElementById("screeningResults").classList.add("d-none");
            document.getElementById("copyScreeningAnswers").classList.add("d-none");
            document.getElementById("screeningBack").classList.add("d-none");
            document.getElementById("screeningQuestions").value = "";
            var modal = new bootstrap.Modal(document.getElementById("screeningModal"));
            modal.show();
        });
    });

    var screeningSubmit = document.getElementById("screeningSubmit");
    if (screeningSubmit) {
        screeningSubmit.addEventListener("click", function () {
            var textarea = document.getElementById("screeningQuestions");
            var questions = textarea.value.split("\n").filter(function (q) { return q.trim() !== ""; });
            if (questions.length === 0) return;

            screeningSubmit.disabled = true;
            screeningSubmit.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Generating...';

            csrfFetch("/jobs/screening-answers", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: screeningJobData.title,
                    company: screeningJobData.company,
                    description: screeningJobData.description,
                    questions: questions,
                }),
            })
                .then(function (resp) { return resp.json(); })
                .then(function (data) {
                    screeningSubmit.disabled = false;
                    screeningSubmit.textContent = "Generate Answers";

                    if (data.error) {
                        alert(data.error);
                        return;
                    }

                    var html = "";
                    data.answers.forEach(function (qa) {
                        html += '<div class="card mb-2"><div class="card-body">';
                        html += '<p class="fw-bold mb-1">' + qa.question + '</p>';
                        html += '<p class="mb-0">' + qa.answer + '</p>';
                        html += '</div></div>';
                    });

                    document.getElementById("screeningAnswersList").innerHTML = html;
                    document.getElementById("screeningInput").classList.add("d-none");
                    document.getElementById("screeningResults").classList.remove("d-none");
                    document.getElementById("copyScreeningAnswers").classList.remove("d-none");
                    document.getElementById("screeningBack").classList.remove("d-none");
                })
                .catch(function (err) {
                    screeningSubmit.disabled = false;
                    screeningSubmit.textContent = "Generate Answers";
                    alert("Error: " + err.message);
                });
        });
    }

    var screeningBack = document.getElementById("screeningBack");
    if (screeningBack) {
        screeningBack.addEventListener("click", function () {
            document.getElementById("screeningInput").classList.remove("d-none");
            document.getElementById("screeningResults").classList.add("d-none");
            document.getElementById("copyScreeningAnswers").classList.add("d-none");
            screeningBack.classList.add("d-none");
        });
    }

    var copyScreening = document.getElementById("copyScreeningAnswers");
    if (copyScreening) {
        copyScreening.addEventListener("click", function () {
            var cards = document.querySelectorAll("#screeningAnswersList .card-body");
            var text = "";
            cards.forEach(function (card) {
                var q = card.querySelector(".fw-bold").textContent;
                var a = card.querySelector("p:last-child").textContent;
                text += "Q: " + q + "\nA: " + a + "\n\n";
            });
            navigator.clipboard.writeText(text.trim()).then(function () {
                copyScreening.textContent = "Copied!";
                setTimeout(function () { copyScreening.textContent = "Copy All"; }, 2000);
            });
        });
    }

    // --- Application Draft ---
    document.querySelectorAll(".draft-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var title = this.dataset.title || "";
            var company = this.dataset.company || "";
            var description = this.dataset.description || "";
            var originalText = this.textContent;

            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Drafting...';

            csrfFetch("/jobs/application-draft", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: title,
                    company: company,
                    description: description,
                }),
            })
                .then(function (resp) {
                    return resp.json().then(function (data) {
                        return { ok: resp.ok, data: data };
                    });
                })
                .then(function (result) {
                    btn.disabled = false;
                    btn.textContent = originalText;

                    if (!result.ok) {
                        alert(result.data.error || "Failed to generate draft.");
                        return;
                    }

                    var draft = result.data.draft;
                    document.getElementById("draftSummary").textContent = draft.summary || "";

                    var qualsHtml = "<ul>";
                    (draft.key_qualifications || []).forEach(function (q) {
                        qualsHtml += "<li>" + q + "</li>";
                    });
                    qualsHtml += "</ul>";
                    document.getElementById("draftQualifications").innerHTML = qualsHtml;

                    document.getElementById("draftIntro").textContent = draft.cover_letter_intro || "";

                    var skillsHtml = "<ul>";
                    (draft.skills_highlight || []).forEach(function (s) {
                        skillsHtml += "<li>" + s + "</li>";
                    });
                    skillsHtml += "</ul>";
                    document.getElementById("draftSkills").innerHTML = skillsHtml;

                    var expHtml = "<ul>";
                    (draft.experience_highlight || []).forEach(function (e) {
                        expHtml += "<li>" + e + "</li>";
                    });
                    expHtml += "</ul>";
                    document.getElementById("draftExperience").innerHTML = expHtml;

                    var modal = new bootstrap.Modal(document.getElementById("draftModal"));
                    modal.show();
                })
                .catch(function (err) {
                    btn.disabled = false;
                    btn.textContent = originalText;
                    alert("Error generating draft: " + err.message);
                });
        });
    });

    var copyDraft = document.getElementById("copyDraft");
    if (copyDraft) {
        copyDraft.addEventListener("click", function () {
            var summary = document.getElementById("draftSummary").textContent;
            var intro = document.getElementById("draftIntro").textContent;

            var quals = [];
            document.querySelectorAll("#draftQualifications li").forEach(function (li) {
                quals.push("- " + li.textContent);
            });
            var skills = [];
            document.querySelectorAll("#draftSkills li").forEach(function (li) {
                skills.push("- " + li.textContent);
            });
            var exps = [];
            document.querySelectorAll("#draftExperience li").forEach(function (li) {
                exps.push("- " + li.textContent);
            });

            var text = "PROFESSIONAL SUMMARY\n" + summary + "\n\n" +
                "KEY QUALIFICATIONS\n" + quals.join("\n") + "\n\n" +
                "COVER LETTER INTRODUCTION\n" + intro + "\n\n" +
                "SKILLS HIGHLIGHT\n" + skills.join("\n") + "\n\n" +
                "EXPERIENCE HIGHLIGHT\n" + exps.join("\n");

            navigator.clipboard.writeText(text).then(function () {
                copyDraft.textContent = "Copied!";
                setTimeout(function () { copyDraft.textContent = "Copy All"; }, 2000);
            });
        });
    }

    // --- Interview Prep ---
    document.querySelectorAll(".interview-prep-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var title = this.dataset.title || "";
            var company = this.dataset.company || "";
            var description = this.dataset.description || "";
            var originalText = this.textContent;

            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Preparing...';

            csrfFetch("/jobs/interview-prep", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title: title, company: company, description: description }),
            })
                .then(function (resp) {
                    return resp.json().then(function (data) {
                        return { ok: resp.ok, data: data };
                    });
                })
                .then(function (result) {
                    btn.disabled = false;
                    btn.textContent = originalText;

                    if (!result.ok) {
                        alert(result.data.error || "Failed to generate interview prep.");
                        return;
                    }

                    var data = result.data;

                    // Technical questions accordion
                    var techHtml = "";
                    (data.technical_questions || []).forEach(function (q, i) {
                        techHtml += '<div class="accordion-item">' +
                            '<h2 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#techQ' + i + '">' + q.question + '</button></h2>' +
                            '<div id="techQ' + i + '" class="accordion-collapse collapse"><div class="accordion-body">' + q.talking_points + '</div></div></div>';
                    });
                    document.getElementById("techQuestions").innerHTML = techHtml;

                    // Behavioral questions accordion
                    var behHtml = "";
                    (data.behavioral_questions || []).forEach(function (q, i) {
                        behHtml += '<div class="accordion-item">' +
                            '<h2 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#behQ' + i + '">' + q.question + '</button></h2>' +
                            '<div id="behQ' + i + '" class="accordion-collapse collapse"><div class="accordion-body">' + q.talking_points + '</div></div></div>';
                    });
                    document.getElementById("behavioralQuestions").innerHTML = behHtml;

                    // Questions to ask
                    var askHtml = "";
                    (data.questions_to_ask || []).forEach(function (q) {
                        askHtml += "<li>" + q + "</li>";
                    });
                    document.getElementById("questionsToAsk").innerHTML = askHtml;

                    // Company tips
                    var tipsHtml = "";
                    (data.company_research_tips || []).forEach(function (t) {
                        tipsHtml += "<li>" + t + "</li>";
                    });
                    document.getElementById("companyTips").innerHTML = tipsHtml;

                    var modal = new bootstrap.Modal(document.getElementById("interviewPrepModal"));
                    modal.show();
                })
                .catch(function (err) {
                    btn.disabled = false;
                    btn.textContent = originalText;
                    alert("Error: " + err.message);
                });
        });
    });

    // Copy interview prep
    var copyPrep = document.getElementById("copyInterviewPrep");
    if (copyPrep) {
        copyPrep.addEventListener("click", function () {
            var text = "INTERVIEW PREPARATION\n\n";
            text += "TECHNICAL QUESTIONS\n";
            document.querySelectorAll("#techQuestions .accordion-item").forEach(function (item) {
                text += "\nQ: " + item.querySelector(".accordion-button").textContent.trim() + "\n";
                text += "Talking Points: " + item.querySelector(".accordion-body").textContent.trim() + "\n";
            });
            text += "\nBEHAVIORAL QUESTIONS\n";
            document.querySelectorAll("#behavioralQuestions .accordion-item").forEach(function (item) {
                text += "\nQ: " + item.querySelector(".accordion-button").textContent.trim() + "\n";
                text += "Talking Points: " + item.querySelector(".accordion-body").textContent.trim() + "\n";
            });
            text += "\nQUESTIONS TO ASK\n";
            document.querySelectorAll("#questionsToAsk li").forEach(function (li) {
                text += "- " + li.textContent + "\n";
            });
            text += "\nCOMPANY RESEARCH TIPS\n";
            document.querySelectorAll("#companyTips li").forEach(function (li) {
                text += "- " + li.textContent + "\n";
            });
            navigator.clipboard.writeText(text.trim()).then(function () {
                copyPrep.textContent = "Copied!";
                setTimeout(function () { copyPrep.textContent = "Copy All"; }, 2000);
            });
        });
    }

    // --- Search form loading state ---
    var searchForm = document.getElementById("searchForm");
    if (searchForm) {
        searchForm.addEventListener("submit", function () {
            var btn = document.getElementById("searchBtn");
            if (btn) {
                btn.disabled = true;
                btn.innerHTML =
                    '<span class="spinner-border spinner-border-sm me-2"></span>Searching...';
            }
        });
    }
});
