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



  var WORKFLOWS = [

    {

      id: "documentation",

      title: "Documentation",

      label: "DOCUMENTATION",

      accent: "#7C4DFF",

      status: "available",

      headline: "Publish a manual from the assembly you already have.",

      description: "A parts manual takes hours for a small assembly and weeks for a large one. Upload the assembly and ask in one sentence - Sage formats the document to your standards, generates the exploded views with balloon callouts, and builds the BOMs.",

      caps: ["Exploded Views", "Balloon Callouts", "Automatic BOMs", "Publication-Ready PDF"],

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

          pending: true,

          caption: "Sage drafts the operations and maintenance manual, cites every claim to a source, and blocks controlled release until an engineer clears the open items."

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

      headline: "Turn the product itself into the training environment.",

      description: "Guide operators and technicians through assemblies using the CAD you already have. Sage controls the view, highlights components, answers questions and resumes the walkthrough in context.",

      demos: [

        {

          id: "walkthrough",

          title: "Walkthrough",

          media: "assets/videos/workflow_training.mp4",

          poster: "assets/images/workflow_training.jpg",

          caption: "Ask a question and the 3D model becomes a guided tour - camera flying to each part, highlights tracking the explanation.",

          alt: "Guided 3D walkthrough explaining a plant process"

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

      /* a single-demo workflow gets no chooser - :empty hides the row */

      if (wf.demos.length < 2) return;



      for (var i = 0; i < wf.demos.length; i++) {

        (function (index) {

          var btn = el("button", "wf-demo", wf.demos[index].title);

          btn.type = "button";

          btn.setAttribute("role", "tab");

          btn.setAttribute("aria-selected", index === activeDemo ? "true" : "false");

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

      var demoButtons = demosEl.querySelectorAll(".wf-demo");

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

          var btn = el("button", "wf-tab", WORKFLOWS[index].title);

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
