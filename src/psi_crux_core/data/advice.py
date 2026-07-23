"""
Authored recommendation advice — v1 subset (~10 CWV-focused canonical keys). FEAT-003, REQ-REC-003.
Original copy (D-03). Unmapped keys fall back to the live audit's own title/description with
advice_status='pending' (never fabricated). Each entry blends with live measured values at runtime.
"""
from __future__ import annotations

ADVICE: dict[str, dict] = {
    "lcp_phases": {
        "title": "Speed up Largest Contentful Paint",
        "why": "LCP is dominated by four phases (TTFB, load delay, load time, render delay). "
               "The breakdown tells you which phase to attack instead of guessing.",
        "fix_steps": ["Preload the LCP image/font and set fetchpriority=high",
                      "Cut server response time (TTFB) with caching/CDN",
                      "Remove render-blocking resources ahead of the LCP element"],
    },
    "lcp_discovery": {
        "title": "Let the browser discover the LCP image sooner",
        "why": "If the LCP image is lazy-loaded or only referenced in CSS/JS, discovery is delayed.",
        "fix_steps": ["Use a plain <img> with a src (not background-image) for the LCP element",
                      "Remove loading=lazy from the LCP image", "Add a preload hint"],
    },
    "cls_culprits": {
        "title": "Eliminate layout shifts",
        "why": "Unsized media, injected content, and non-composited animations move the page as it loads.",
        "fix_steps": ["Set width/height (or aspect-ratio) on images and video",
                      "Reserve space for ads/embeds/banners",
                      "Animate transform/opacity, not layout properties"],
    },
    "inp_latency": {
        "title": "Reduce Interaction to Next Paint",
        "why": "Long tasks and heavy event handlers delay the visual response to taps/clicks.",
        "fix_steps": ["Break up long tasks; yield to the main thread",
                      "Debounce expensive handlers", "Defer non-critical JS off the interaction path"],
    },
    "render_blocking": {
        "title": "Remove render-blocking resources",
        "why": "Synchronous CSS/JS in the head block first paint.",
        "fix_steps": ["Inline critical CSS, load the rest async",
                      "Defer non-critical scripts", "Preconnect to required origins"],
    },
    "image_delivery": {
        "title": "Optimize image delivery",
        "why": "Oversized, unoptimized, or legacy-format images waste bytes and slow LCP.",
        "fix_steps": ["Serve AVIF/WebP", "Use responsive srcset for the actual display size",
                      "Compress and lazy-load below-the-fold images"],
    },
    "js_unused": {
        "title": "Cut unused JavaScript",
        "why": "Unused JS is downloaded, parsed, and compiled for nothing.",
        "fix_steps": ["Code-split by route", "Tree-shake and drop unused dependencies",
                      "Load third-party widgets on interaction"],
    },
    "third_party_impact": {
        "title": "Tame third-party impact",
        "why": "Third-party scripts block the main thread and add unpredictable network cost.",
        "fix_steps": ["Lazy-load or facade non-critical embeds",
                      "Self-host critical third-party assets", "Audit tag-manager tags"],
    },
    "document_latency": {
        "title": "Lower document latency (TTFB)",
        "why": "Slow server responses, redirects, and uncompressed HTML delay everything downstream.",
        "fix_steps": ["Enable text compression (Brotli/gzip)",
                      "Cache HTML at the edge", "Remove landing-page redirects"],
    },
    "cache_policy": {
        "title": "Set an efficient cache policy",
        "why": "Short cache lifetimes force repeat downloads of static assets.",
        "fix_steps": ["Set long max-age + immutable on fingerprinted assets",
                      "Use a CDN with proper cache headers"],
    },
}
