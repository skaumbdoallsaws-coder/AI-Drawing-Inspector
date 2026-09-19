/* InspectorPro marketing site - progressive enhancement.
   Two jobs only:
     1. reveal .fade-in elements as they scroll into view
     2. drive the mobile nav (CSS shows it via .mobile-nav.open)
   In-page anchor scrolling is handled by CSS (scroll-behavior + scroll-margin-top),
   so there is deliberately no scroll code here. */
(function () {
  "use strict";

  var MOBILE_BREAKPOINT = 900; /* must match the @media rule in css/style.css */

  /* ---------- 1. Scroll reveal ---------- */

  function initReveal() {
    var targets = document.querySelectorAll(".fade-in");
    if (!targets.length) return;

    function revealAll() {
      for (var i = 0; i < targets.length; i++) {
        targets[i].classList.add("visible");
      }
    }

    /* Respect reduced-motion, and degrade gracefully on browsers without
       IntersectionObserver: in both cases show the content immediately
       rather than leaving it stuck at opacity 0. */
    var reduceMotion =
      window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion || typeof window.IntersectionObserver !== "function") {
      revealAll();
      return;
    }

    var observer = new window.IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i++) {
          var entry = entries[i];
          if (!entry.isIntersecting) continue;
          entry.target.classList.add("visible");
          observer.unobserve(entry.target); /* reveal once, then stop watching */
        }
      },
      { root: null, rootMargin: "0px 0px -10% 0px", threshold: 0.05 }
    );

    for (var i = 0; i < targets.length; i++) {
      observer.observe(targets[i]);
    }
  }

  /* ---------- 2. Mobile nav ---------- */

  function initMobileNav() {
    var btn = document.getElementById("mobileMenuBtn");
    var nav = document.getElementById("mobileNav");
    if (!btn || !nav) return;

    if (!nav.id) nav.id = "mobileNav";
    btn.setAttribute("aria-controls", nav.id);
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-label", "Toggle navigation menu");

    function setOpen(open) {
      nav.classList.toggle("open", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    }

    function isOpen() {
      return nav.classList.contains("open");
    }

    btn.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation(); /* keep the document handler below from closing it again */
      setOpen(!isOpen());
    });

    /* Every link in the drawer navigates within the page, so the drawer
       would otherwise stay open on top of the destination. */
    nav.addEventListener("click", function (event) {
      if (event.target.closest("a")) setOpen(false);
    });

    document.addEventListener("click", function (event) {
      if (!isOpen()) return;
      if (nav.contains(event.target) || btn.contains(event.target)) return;
      setOpen(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen()) {
        setOpen(false);
        btn.focus();
      }
    });

    /* Past the breakpoint the drawer is display:none but would keep .open,
       so it would reappear on the way back down without this. */
    window.addEventListener("resize", function () {
      if (window.innerWidth > MOBILE_BREAKPOINT && isOpen()) setOpen(false);
    });
  }

  /* ---------- 3. Play videos only while they are on screen ---------- */

  /* Module-scoped so panels built after init (the workflow showcase swaps its
     clip in on demand) can register a video with the same observer. */
  var videoObserver = null;

  function initVideoGating() {
    if (typeof window.IntersectionObserver !== 'function') return;

    /* Without this every panel decodes and loops continuously, which on this
       page means eight clips at once - enough to bog down a laptop and to burn
       phone data on a connection that will never see most of them. */
    videoObserver = new window.IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i++) {
          var video = entries[i].target;
          if (entries[i].isIntersecting) {
            /* play() rejects if autoplay is blocked; the poster stays up, which
               is the correct fallback, so the rejection is intentionally ignored */
            var played = video.play();
            if (played && typeof played.catch === 'function') played.catch(function () {});
          } else if (!video.paused) {
            video.pause();
          }
        }
      },
      { root: null, rootMargin: '200px 0px', threshold: 0.01 }
    );

    var videos = document.querySelectorAll('video');
    for (var i = 0; i < videos.length; i++) observeVideo(videos[i]);
  }

  function observeVideo(video) {
    /* No observer (old browser): try to play and let the poster stand in if
       autoplay is refused. */
    if (!videoObserver) {
      var played = video.play();
      if (played && typeof played.catch === 'function') played.catch(function () {});
      return;
    }
    /* Only the hero is worth fetching up front. */
    if (video.getAttribute('preload') !== 'auto') video.preload = 'none';
    videoObserver.observe(video);
  }

  /* ---------- 4. Early-reaction marquee ---------- */

  /* Add new reactions here only - the rows build themselves from this list.
     These are responses to public demos, not customer testimonials, so no
     surname, employer, photo, or profile link is ever rendered. */
  var REACTIONS = [
    {
      quote: "Reducing planning time directly improves production agility, allowing teams to focus on complex issues and continuous improvement.",
      name: "Ashish K.",
      role: "Industrial Projects & Manufacturing Operations",
      initials: "AK",
      context: "Reaction to an InspectorPro demo"
    },
    {
      quote: "I see this as a marriage of quality and design. The software could show why each characteristic must be controlled and what physically happens when it falls out of specification.",
      name: "Michael L.",
      role: "Dimensional Engineer",
      initials: "ML",
      context: "Reaction to an InspectorPro demo"
    }
  ];

  function reactionCard(item) {
    var el = document.createElement('article');
    el.className = 'reaction-card';

    var label = document.createElement('div');
    label.className = 'reaction-card__label';
    label.textContent = item.context;

    var quote = document.createElement('blockquote');
    quote.textContent = item.quote;

    var avatar = document.createElement('div');
    avatar.className = 'reaction-card__avatar';
    avatar.setAttribute('aria-hidden', 'true');  /* decorative: name follows in text */
    avatar.textContent = item.initials;

    var name = document.createElement('div');
    name.className = 'reaction-card__name';
    name.textContent = item.name;

    var role = document.createElement('div');
    role.className = 'reaction-card__role';
    role.textContent = item.role;

    var who = document.createElement('div');
    who.appendChild(name);
    who.appendChild(role);

    var foot = document.createElement('footer');
    foot.appendChild(avatar);
    foot.appendChild(who);

    el.appendChild(label);
    el.appendChild(quote);
    el.appendChild(foot);
    return el;
  }

  function initReactions() {
    var rows = document.querySelectorAll('[data-reaction-row]');
    if (!rows.length || !REACTIONS.length) return;

    /* Repeat the small set so one group is always wider than the viewport;
       without that the loop shows empty space before it wraps. */
    var REPEATS = 4;

    for (var r = 0; r < rows.length; r++) {
      var track = rows[r].querySelector('.reaction-marquee__track');
      if (!track) continue;

      /* offset the second row's starting card so the two rows do not read
         as the same sequence sliding past in opposite directions */
      var offset = Number(rows[r].getAttribute('data-reaction-row')) || 0;

      var group = document.createElement('div');
      group.className = 'reaction-marquee__group';
      for (var i = 0; i < REPEATS * REACTIONS.length; i++) {
        group.appendChild(reactionCard(REACTIONS[(i + offset) % REACTIONS.length]));
      }

      /* the clone exists purely to make the wrap seamless */
      var clone = group.cloneNode(true);
      clone.setAttribute('aria-hidden', 'true');

      track.appendChild(group);
      track.appendChild(clone);
    }
  }

  /* ---------- 5. Connected workflows showcase ----------

     ADD A WORKFLOW OR A DEMO BY EDITING THIS LIST ONLY.
     The tabs, the copy, the monitor and the demo row all build themselves
     from it - there is no per-workflow markup to touch.

     workflow: { id, title, label, accent, status, headline, description,
                 caps[], demos[] }
     demo:     { id, title, caption, media, poster, alt }
               ...or { id, title, caption, pending: true } when the recording
               does not exist yet, which renders an honest placeholder rather
               than showing some other clip under the wrong label.

     Keep every string ASCII - this file has been through a mojibake repair. */

  /* ---- workflow + document-type icons ----

     Inlined rather than <img> on purpose: every glyph is drawn in
     currentColor, so an inline node inherits the tab or card text color
     and the active/inactive states need no second asset. 24x24 viewBox,
     sized by CSS. Source: InspectorPro_Web_Tab_Icons, icon-map.json. */

  var WF_ICONS = {
    "Documentation":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <rect x="5" y="3" width="12" height="16" rx="2.4" fill="currentColor" opacity=".10"/> <path d="M8 3.8h7.2L19 7.6V19a2 2 0 0 1-2 2H8a3 3 0 0 1-3-3V6.8a3 3 0 0 1 3-3Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/> <path d="M15 4v4h4M8.3 11h7.4M8.3 14.5h7.4M8.3 18h4.4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/> </svg>',
    "Vendor Response":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <path d="M4.2 6.2h5.1l2.1 2.2h8.4v8.4a2 2 0 0 1-2 2H6.2a2 2 0 0 1-2-2V6.2Z" fill="currentColor" opacity=".09"/> <path d="M3.5 6h5l2.2 2.3h9.8v8.4a2.3 2.3 0 0 1-2.3 2.3H5.8a2.3 2.3 0 0 1-2.3-2.3V6Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/> <path d="m8.1 14.2 2.1 2.1 5.3-5.3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/> </svg>',
    "Training":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <path d="m12 3 9 4.6-9 4.6L3 7.6 12 3Z" fill="currentColor" opacity=".10"/> <path d="m12 3 9 4.6-9 4.6L3 7.6 12 3Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/> <path d="M6.4 9.5v5.1c0 2 2.6 3.7 5.6 3.7s5.6-1.7 5.6-3.7V9.5M21 8v5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/> <circle cx="21" cy="14.8" r="1" fill="currentColor"/> </svg>',
    "Process Maps":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <circle cx="5" cy="6" r="2.3" fill="currentColor" opacity=".12"/> <circle cx="19" cy="12" r="2.3" fill="currentColor" opacity=".12"/> <circle cx="7" cy="19" r="2.3" fill="currentColor" opacity=".12"/> <circle cx="5" cy="6" r="2.3" stroke="currentColor" stroke-width="1.7"/> <circle cx="19" cy="12" r="2.3" stroke="currentColor" stroke-width="1.7"/> <circle cx="7" cy="19" r="2.3" stroke="currentColor" stroke-width="1.7"/> <path d="M7.2 6.5c4.5.4 5.3 3.7 9.5 4.9M17 13.5c-2.4 2.8-4.8 4.5-7.8 5.1M5.5 8.3c-.2 3 .1 5.3.8 8.3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/> </svg>',
    "Facility Layout":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <rect x="3.5" y="4" width="17" height="16" rx="2.2" fill="currentColor" opacity=".08"/> <rect x="3.5" y="4" width="17" height="16" rx="2.2" stroke="currentColor" stroke-width="1.7"/> <path d="M8 4v6h5V4M13 10v4h7.5M3.5 14H9v6" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/> <path d="M15.7 16.8h2.1M15.7 18.7h2.1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/> </svg>',
    "Drawing Release":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <path d="M6 3.5h8l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 5 20V5a1.5 1.5 0 0 1 1-1.5Z" fill="currentColor" opacity=".09"/> <path d="M6 3.5h8l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 5 20V5A1.5 1.5 0 0 1 6 3.5ZM14 3.8v4h4" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/> <path d="m8.4 14.6 2.1 2.1 4.9-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/> </svg>',
    "Revision Compare":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <path d="M6 4.5v15M18 4.5v15" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" opacity=".45"/> <path d="M9 7h6.8l-2-2M15.8 7l-2 2M15 17H8.2l2 2M8.2 17l2-2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/> <circle cx="6" cy="7" r="2" fill="currentColor" opacity=".12"/> <circle cx="18" cy="17" r="2" fill="currentColor" opacity=".12"/> <circle cx="6" cy="7" r="2" stroke="currentColor" stroke-width="1.7"/> <circle cx="18" cy="17" r="2" stroke="currentColor" stroke-width="1.7"/> </svg>',
    "Parts Manual":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <path d="M4.2 5.5A2.5 2.5 0 0 1 6.7 3H11v16H6.7a2.5 2.5 0 0 0-2.5 2.5v-16Z" fill="currentColor" opacity=".11"/> <path d="M19.8 5.5A2.5 2.5 0 0 0 17.3 3H13v16h4.3a2.5 2.5 0 0 1 2.5 2.5v-16Z" fill="currentColor" opacity=".06"/> <path d="M4.2 5.5A2.5 2.5 0 0 1 6.7 3H11v16H6.7a2.5 2.5 0 0 0-2.5 2.5v-16ZM19.8 5.5A2.5 2.5 0 0 0 17.3 3H13v16h4.3a2.5 2.5 0 0 1 2.5 2.5v-16Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/> <path d="M6.7 7h1.9M6.7 10h1.9M15.4 7h1.9M15.4 10h1.9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/> </svg>',
    "Operations Manual":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <path d="M5 4h9a2 2 0 0 1 2 2v12H7a2 2 0 0 0-2 2V4Z" fill="currentColor" opacity=".08"/> <path d="M5 4h9a2 2 0 0 1 2 2v12H7a2 2 0 0 0-2 2V4Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/> <path d="M16.8 10.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6Z" fill="currentColor" opacity=".12"/> <path d="M16.8 10.2v-1.4M16.8 19.2v-1.4M12.3 14h-1.4M22.7 14h-2.1M13.6 10.8l-1-1M20 17.2l1 1M20 10.8l1-1M13.6 17.2l-1 1" stroke="currentColor" stroke-width="1.35" stroke-linecap="round"/> <circle cx="16.8" cy="14" r="1.55" stroke="currentColor" stroke-width="1.6"/> </svg>',
    "Specification Sheet":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <rect x="5" y="4" width="14" height="17" rx="2" fill="currentColor" opacity=".08"/> <rect x="5" y="4" width="14" height="17" rx="2" stroke="currentColor" stroke-width="1.7"/> <path d="M9 4V2.8h6V4M8.5 9h7M8.5 13h2.2M13.3 13h2.2M8.5 17h2.2M13.3 17h2.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/> </svg>',
    "Work Instructions":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <path d="M13.8 5.2a4.2 4.2 0 0 0-5.5 5.4L3.7 15.2a2.5 2.5 0 1 0 3.5 3.5l4.6-4.6a4.2 4.2 0 0 0 5.5-5.4l-2.6 2.6-2.4-.6-.6-2.4 2.1-3.1Z" fill="currentColor" opacity=".10"/> <path d="M13.8 5.2a4.2 4.2 0 0 0-5.5 5.4L3.7 15.2a2.5 2.5 0 1 0 3.5 3.5l4.6-4.6a4.2 4.2 0 0 0 5.5-5.4l-2.6 2.6-2.4-.6-.6-2.4 2.1-3.1Z" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/> <path d="M15.5 17h5M15.5 20h3.3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/> </svg>',
    "Inspection Sheet":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <rect x="5" y="4" width="14" height="17" rx="2" fill="currentColor" opacity=".08"/> <rect x="5" y="4" width="14" height="17" rx="2" stroke="currentColor" stroke-width="1.7"/> <path d="M9 4V2.8h6V4M8.2 10.2l1.2 1.2 2.2-2.3M13.7 10.4h2.3M8.2 15.4l1.2 1.2 2.2-2.3M13.7 15.6h2.3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/> </svg>',
    "Process Explanation":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <path d="M4 5.5h16A1.5 1.5 0 0 1 21.5 7v8a1.5 1.5 0 0 1-1.5 1.5h-7.2L9 20.2V16.5H4A1.5 1.5 0 0 1 2.5 15V7A1.5 1.5 0 0 1 4 5.5Z" fill="currentColor" opacity=".10"/> <path d="M4 5.5h16A1.5 1.5 0 0 1 21.5 7v8a1.5 1.5 0 0 1-1.5 1.5h-7.2L9 20.2V16.5H4A1.5 1.5 0 0 1 2.5 15V7A1.5 1.5 0 0 1 4 5.5Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/> <path d="m10.4 8.6 4.6 2.5-4.6 2.5V8.6Z" fill="currentColor"/> </svg>',
    "Access & Clearance":
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" aria-hidden="true"> <rect x="3" y="3.4" width="18" height="3" rx="1" fill="currentColor" opacity=".10"/> <rect x="3" y="3.4" width="18" height="3" rx="1" stroke="currentColor" stroke-width="1.7"/> <path d="M3.9 20.6h16.2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/> <path d="M7 9v8.6M5.4 10.3 7 8.7l1.6 1.6M5.4 16.3 7 17.9l1.6-1.6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/> <circle cx="15.4" cy="12.3" r="1.8" stroke="currentColor" stroke-width="1.6"/> <path d="M12.8 20.5v-2.1a2.6 2.6 0 0 1 5.2 0v2.1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/> </svg>'
  };

  var WORKFLOWS = [
    {
      id: "documentation",
      title: "Documentation",
      label: "DOCUMENTATION",
      accent: "#7C4DFF",
      status: "available",
      /* Shared by every demo in this workflow, so it has to stay true of both
         a parts manual and an operations manual. Per-manual specifics live in
         each demo caption. No caps line: there is no honest four-item list
         common to both document types. */
      headline: "Publish the manual from the assembly you already have.",
      description: "Manuals are weeks of production work: laying out figures, chasing callouts, reformatting after every revision. InspectorPro builds the document from connected product data and shows the evidence behind each page.",
      demos: [
        {
          id: "parts-manual",
          title: "Parts Manual",
          media: "assets/videos/workflow_parts_manual_v1.mp4",
          poster: "assets/images/workflow_parts_manual_v1.jpg",
          caption: "One typed sentence compiles the pages, captures exploded illustrations with numbered balloon callouts, builds the BOM for each figure, and publishes the PDF.",
          alt: "Generating an illustrated parts manual in InspectorPro: one typed sentence asks Sage to generate and publish a parts manual for the active assembly, which compiles the pages, captures exploded technical illustrations with numbered balloon callouts, builds the bill of materials for each figure, and publishes a fifteen-page PDF with a table of contents"
        },
        {
          id: "operations-manual",
          title: "Operations Manual",
          media: "assets/videos/workflow_operations_manual_v1.mp4",
          poster: "assets/images/workflow_operations_manual_v1.jpg",
          caption: "Thirty-three pages with every claim cited to a source - and controlled release stays blocked until an engineer clears the open items.",
          alt: "Generating an operations and maintenance manual in InspectorPro: Sage compiles the MMLE-50D Electric Mobile Lift operations and maintenance manual, captures the technical figures from the assembly, cites each claim to a registered source, and marks the document DRAFT while controlled release remains blocked"
        },
        /* The three below are awaiting recordings. When a clip lands, replace
           `pending: true` with `media`, `poster` and `alt` - nothing else
           changes. Keep the two shipped demos first so the workflow always
           opens on a real video rather than a placeholder. */
        {
          id: "specification-sheet",
          title: "Specification Sheet",
          media: "assets/videos/workflow_specification_sheet_v1.mp4",
          poster: "assets/images/workflow_specification_sheet_v1.jpg",
          caption: "One page, nine approved product claims - each cited to a source: the manufacturer product page, the CAD extraction, and the reviewed assembly registry.",
          alt: "Generating a product specification sheet in InspectorPro: Sage builds a one-page MMLE-50D Electric Mobile Lift specification with a fresh assembled-product capture, a rated capacity and travel table, and nine approved product claims, then reports the three sources cited and confirms no source CAD geometry was changed"
        },
        {
          id: "work-instructions",
          title: "Work Instructions",
          pending: true,
          caption: "Assembly work instructions staged step by step from the build sequence - numbered callouts identifying the parts handled at each stage, with station, completion check and open items named."
        },
        {
          id: "inspection-sheet",
          title: "Inspection Sheet",
          pending: true,
          caption: "An inspection sheet ballooned straight from the drawing: every controlled characteristic numbered, ready for measured values and tolerances entered by the inspector."
        }
      ]
    },
    {
      id: "vendor-response",
      title: "Vendor Response",
      label: "VENDOR &amp; CUSTOMER RESPONSE",
      accent: "#4fc3f7",
      status: "available",
      headline: "Answer vendor questions before they turn into production delays.",
      description: "A vendor asks a question and the line waits on the reply. InspectorPro answers directly from connected product context, so engineers stop rebuilding the background from the drawing, the model, the assembly and the inspection report every time.",
      demos: [
        {
          id: "supplier-qa",
          title: "Supplier Q and A",
          media: "assets/videos/workflow_vendor_response.mp4",
          poster: "assets/images/workflow_vendor_response.png",
          caption: "The answer is assembled from connected product context while the question still matters.",
          alt: "Answering a vendor question from connected product context"
        }
        /* Further recordings drop in here as siblings, for example:
        , { id: "deviation-analysis", title: "Deviation Analysis",
            media: "assets/videos/workflow_deviation_analysis.mp4",
            poster: "assets/images/workflow_deviation_analysis.jpg",
            caption: "...", alt: "..." }
        , { id: "part-context", title: "Part Context", ... } */
      ]
    },
    {
      id: "training",
      title: "Training",
      label: "TRAINING",
      accent: "#00E676",
      status: "available",
      /* Shared by both demos, so it has to stay true of a narrated process
         explanation and a first-person access check alike. The specifics of
         each - who is being taught, versus what is being measured - live in
         the per-demo captions. */
      headline: "Turn the product itself into the training environment.",
      description: "Operators and technicians learn on the CAD you already have. Sage explains the process and controls the view, and the same model answers whether a person can physically reach the work.",
      pickerLabel: "Choose a view",
      demos: [
        {
          id: "process-explanation",
          title: "Process Explanation",
          media: "assets/videos/workflow_training.mp4",
          poster: "assets/images/workflow_training.jpg",
          caption: "Ask a question and the 3D model becomes a guided tour - camera flying to each part, highlights tracking the explanation.",
          alt: "Guided 3D walkthrough explaining a plant process"
        },
        {
          id: "access-clearance",
          title: "Access & Clearance",
          media: "assets/videos/workflow_access_clearance_v1.mp4",
          poster: "assets/images/workflow_access_clearance_v1.jpg",
          caption: "Walk the plant at human scale - 1.95 m standing, real collision. Under the structure the model stops you: clearance is 1.36 m, so the job is done kneeling.",
          alt: "First-person walkthrough of a cooling tower at human scale in InspectorPro: walking the service platform and stairs, then crawling under the structure where the heads-up display refuses the stand command and reports that geometry clearance is 1.36 metres while standing requires 1.95 metres"
        }
        /* , { id: "ask-sage", title: "Ask Sage", ... }
           , { id: "isolation", title: "Component Isolation", ... } */
      ]
    },
    {
      id: "process-maps",
      title: "Process Maps",
      label: "PROCESS MAPS",
      accent: "#FFB300",
      status: "available",
      headline: "Generate step-by-step process maps from your assembly.",
      description: "The build sequence is implied across the assembly structure and the documents around it, but nobody has drawn the map. InspectorPro proposes the process step by step, with the CAD evidence behind each one.",
      demos: [
        {
          id: "build-sequence",
          title: "Build Sequence",
          media: "assets/videos/workflow_process_map.mp4",
          poster: "assets/images/workflow_process_map.png",
          caption: "Edit what it proposes - the map stays tied to the model it came from.",
          alt: "A step-by-step build process map generated from the assembly, with CAD evidence behind each step"
        }
      ]
    },
    {
      id: "facility-layout",
      title: "Facility Layout",
      label: "FACILITY LAYOUT",
      accent: "#FF5252",
      status: "pilot",
      headline: "Build facility layouts with an agent.",
      description: "Go from layout intent to a first pass in minutes. Sage arranges equipment, production cells, zones, aisles and material flow at real-world scale - then analyzes and iterates the same layout with you.",
      caps: ["2D Planning", "3D Walkthrough", "Drone Exploration", "Spatial Analysis"],
      demos: [
        {
          id: "layout-agent",
          title: "Layout Agent",
          media: "assets/videos/workflow_facility_agent_v2.mp4",
          poster: "assets/images/workflow_facility_agent_v2.jpg",
          caption: "Plan the floor in 2D, fly it with the drone view, walk it at ground level, then ask Sage to rank departments by equipment footprint.",
          alt: "Four stages of an InspectorPro facility layout: planning the floor in 2D from a library of real assets, flying the layout with the drone view, walking it at ground level, then asking Sage to rank six departments by physical equipment-footprint coverage, which returns a written finding and a bar chart"
        }
      ]
    },
    {
      id: "drawing-release",
      title: "Drawing Release",
      label: "DRAWING RELEASE CHECK",
      accent: "#4fc3f7",
      status: "available",
      headline: "Check drawings against the 3D model before release.",
      description: "InspectorPro compares the drawing to the CAD model feature by feature - missing dimensions, tolerance gaps, incorrect views, uncalled-out holes - and checks that your drawing standards are actually applied.",
      demos: [
        {
          id: "completeness",
          title: "Completeness",
          media: "assets/videos/workflow_drawing_check.mp4",
          poster: "assets/images/workflow_drawing_check.jpg",
          caption: "Each feature is identified from the 3D model, not inferred from the drawing, so problems get caught before release instead of on the floor.",
          alt: "Checking a drawing against the 3D model and drawing standards"
        }
        /* , { id: "model-vs-drawing", title: "Model vs Drawing", ... }
           , { id: "standards", title: "Standards", ... } */
      ]
    },
    {
      id: "revision-compare",
      title: "Revision Compare",
      label: "REVISION COMPARISON",
      accent: "#FF5252",
      status: "available",
      headline: "Compare drawings, models and assemblies across revisions.",
      description: "Load Rev A and Rev B side by side. Removed features light up red, added green, modified amber - using CAD feature identity rather than a pixel overlay.",
      demos: [
        {
          id: "drawing-revision",
          title: "Drawing Revision",
          media: "assets/videos/workflow_rev_compare.mp4",
          poster: "assets/images/workflow_rev_compare.jpg",
          caption: "It can tell you a specific flange was extended from 44.45mm to 76.2mm, not just that something moved.",
          alt: "Comparing two drawing revisions side by side with the changed callout highlighted"
        }
        /* , { id: "part-revision", title: "Part Revision", ... }
           , { id: "assembly-revision", title: "Assembly Revision", ... } */
      ]
    }
  ];

  var BADGE_TEXT = { available: "Available", pilot: "Pilot" };

  function prefersReducedMotion() {
    return typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function initWorkflowShowcase() {
    var root = document.querySelector("[data-wf-showcase]");
    if (!root || !WORKFLOWS.length) return;

    var tabsEl = root.querySelector("[data-wf-tabs]");
    var stageEl = root.querySelector(".wf-stage");
    var copyEl = root.querySelector("[data-wf-copy]");
    var screenEl = root.querySelector("[data-wf-screen]");
    var demosEl = root.querySelector("[data-wf-demos]");
    var pickerEl = root.querySelector("[data-wf-picker]");
    var pickerLabelEl = root.querySelector("[data-wf-picker-label]");
    var captionEl = root.querySelector("[data-wf-caption]");
    if (!tabsEl || !stageEl || !copyEl || !screenEl || !demosEl || !captionEl) return;

    /* the fallback copy only exists for crawlers and no-JS visitors */
    var fallback = root.parentNode.querySelector("[data-wf-fallback]");
    if (fallback && fallback.parentNode) fallback.parentNode.removeChild(fallback);
    root.hidden = false;

    var activeWorkflow = 0;
    var activeDemo = 0;

    function el(tag, cls, text) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text != null) node.textContent = text;
      return node;
    }

    /* The glyph is trusted markup from the bundled icon set, never user or
       model input, so innerHTML is safe here. A missing label yields no icon
       rather than an empty box. */
    function iconFor(label, cls) {
      var markup = WF_ICONS[label];
      if (!markup) return null;
      var node = el("span", cls);
      node.setAttribute("aria-hidden", "true");
      node.innerHTML = markup;
      return node;
    }

    /* Only the panels swap. The monitor itself never moves, which is the
       point of the section: one context, many workflows. */
    function swap(node, build) {
      if (prefersReducedMotion()) { build(); return; }
      node.classList.add("is-swapping");
      window.setTimeout(function () {
        build();
        node.classList.remove("is-swapping");
      }, 150);
    }

    function renderCopy() {
      var wf = WORKFLOWS[activeWorkflow];
      copyEl.innerHTML = "";

      var label = el("div", "feature-label");
      label.style.color = wf.accent;
      /* label may carry an entity such as &amp; */
      label.innerHTML = wf.label;
      if (wf.status && BADGE_TEXT[wf.status]) {
        label.appendChild(el("span", "wf-badge " + wf.status, BADGE_TEXT[wf.status]));
      }
      copyEl.appendChild(label);

      copyEl.appendChild(el("h3", null, wf.headline));
      copyEl.appendChild(el("p", null, wf.description));

      if (wf.caps && wf.caps.length) {
        var caps = el("p", "feature-caps");
        for (var i = 0; i < wf.caps.length; i++) {
          if (i) {
            /* real whitespace around the separator so the line wraps between
               capabilities and never inside one */
            caps.appendChild(document.createTextNode(" "));
            caps.appendChild(el("span", null, "\u00b7"));
            caps.appendChild(document.createTextNode(" "));
          }
          caps.appendChild(el("b", null, wf.caps[i]));
        }
        copyEl.appendChild(caps);
      }
    }

    function renderScreen() {
      var demo = WORKFLOWS[activeWorkflow].demos[activeDemo];
      screenEl.innerHTML = "";

      if (demo.pending) {
        var panel = el("div", "wf-pending");
        panel.appendChild(el("div", "wf-pending-badge", "Demo recording"));
        /* the caption under the monitor already carries the description, so
           the screen itself only says why it is empty */
        panel.appendChild(el("div", "wf-pending-text",
          demo.pendingText || "This walkthrough is being recorded now."));
        screenEl.appendChild(panel);
        return;
      }

      var video = document.createElement("video");
      video.src = demo.media;
      if (demo.poster) video.poster = demo.poster;
      video.loop = true;
      video.muted = true;
      video.autoplay = true;
      video.setAttribute("playsinline", "");
      video.setAttribute("preload", "none");
      if (demo.alt) video.setAttribute("aria-label", demo.alt);
      screenEl.appendChild(video);
      observeVideo(video);
    }

    function renderDemos() {
      var wf = WORKFLOWS[activeWorkflow];
      demosEl.innerHTML = "";
      /* One output means there is nothing to choose between, so the whole
         picker - heading included - stays out of the page. */
      if (pickerEl) pickerEl.hidden = wf.demos.length < 2;
      if (wf.demos.length < 2) return;
      /* the grid sizes its tracks from the count, so two cards fill the
         column instead of huddling in the first two of five */
      demosEl.style.setProperty("--wf-doc-count", String(wf.demos.length));
      var pickerText = wf.pickerLabel || "Choose a document type";
      if (pickerLabelEl) pickerLabelEl.textContent = pickerText;
      demosEl.setAttribute("aria-label", pickerText);

      for (var i = 0; i < wf.demos.length; i++) {
        (function (index) {
          var demo = wf.demos[index];
          var btn = el("button", "wf-doc");
          btn.type = "button";
          btn.setAttribute("role", "tab");
          btn.setAttribute("aria-selected", index === activeDemo ? "true" : "false");
          var docIcon = iconFor(demo.title, "wf-doc-icon");
          if (docIcon) btn.appendChild(docIcon);
          btn.appendChild(el("span", "wf-doc-text", demo.title));
          btn.addEventListener("click", function () { selectDemo(index); });
          demosEl.appendChild(btn);
        })(i);
      }
    }

    function renderCaption() {
      captionEl.textContent = WORKFLOWS[activeWorkflow].demos[activeDemo].caption || "";
    }

    function syncTabs() {
      var buttons = tabsEl.querySelectorAll(".wf-tab");
      for (var i = 0; i < buttons.length; i++) {
        buttons[i].setAttribute("aria-selected", i === activeWorkflow ? "true" : "false");
        buttons[i].tabIndex = i === activeWorkflow ? 0 : -1;
      }
    }

    function selectDemo(index) {
      if (index === activeDemo) return;
      activeDemo = index;
      var demoButtons = demosEl.querySelectorAll(".wf-doc");
      for (var i = 0; i < demoButtons.length; i++) {
        demoButtons[i].setAttribute("aria-selected", i === activeDemo ? "true" : "false");
      }
      /* the workflow tab and its copy stay exactly as they are */
      swap(screenEl, function () { renderScreen(); renderCaption(); });
    }

    function selectWorkflow(index, focusTab) {
      if (index < 0 || index >= WORKFLOWS.length) return;
      activeWorkflow = index;
      activeDemo = 0;
      syncTabs();
      swap(stageEl, function () {
        renderCopy();
        renderScreen();
        renderDemos();
        renderCaption();
      });
      if (focusTab) {
        var btn = tabsEl.querySelectorAll(".wf-tab")[index];
        if (btn) btn.focus();
      }
    }

    function buildTabs() {
      for (var i = 0; i < WORKFLOWS.length; i++) {
        (function (index) {
          var btn = el("button", "wf-tab");
          var tabIcon = iconFor(WORKFLOWS[index].title, "wf-tab-icon");
          if (tabIcon) btn.appendChild(tabIcon);
          btn.appendChild(el("span", "wf-tab-text", WORKFLOWS[index].title));
          btn.type = "button";
          btn.setAttribute("role", "tab");
          btn.id = "wf-tab-" + WORKFLOWS[index].id;
          btn.addEventListener("click", function () { selectWorkflow(index, false); });
          btn.addEventListener("keydown", function (event) {
            var next = null;
            if (event.key === "ArrowRight") next = (index + 1) % WORKFLOWS.length;
            else if (event.key === "ArrowLeft") next = (index - 1 + WORKFLOWS.length) % WORKFLOWS.length;
            else if (event.key === "Home") next = 0;
            else if (event.key === "End") next = WORKFLOWS.length - 1;
            if (next === null) return;
            event.preventDefault();
            selectWorkflow(next, true);
          });
          tabsEl.appendChild(btn);
        })(i);
      }
    }

    function indexFromHash() {
      var hash = (window.location.hash || "").replace("#", "").toLowerCase();
      if (!hash) return -1;
      for (var i = 0; i < WORKFLOWS.length; i++) {
        if (WORKFLOWS[i].id === hash) return i;
      }
      return -1;
    }

    buildTabs();
    /* a deep link such as #documentation opens on that workflow; #demos and
       #features keep their existing meaning of "the showcase" */
    var fromHash = indexFromHash();
    activeWorkflow = fromHash >= 0 ? fromHash : 0;
    syncTabs();
    renderCopy();
    renderScreen();
    renderDemos();
    renderCaption();

    window.addEventListener("hashchange", function () {
      var index = indexFromHash();
      if (index >= 0 && index !== activeWorkflow) selectWorkflow(index, false);
    });
  }

  function init() {
    initReveal();
    initMobileNav();
    initVideoGating();
    initReactions();
    initWorkflowShowcase();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
