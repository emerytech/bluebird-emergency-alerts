/* bb-safe.js — Global error safety layer for BlueBird Admin UI */
(function () {
  'use strict';

  // Global uncaught error handler — logs but never crashes the UI
  window.addEventListener('error', function (e) {
    console.error('[BB ERROR]', e.message, e.filename + ':' + e.lineno);
  });

  window.addEventListener('unhandledrejection', function (e) {
    console.error('[BB PROMISE]', e.reason);
  });

  /**
   * safeRun(name, fn) — execute fn() and swallow any exception.
   * UI-critical paths should use this so a JS bug never freezes the page.
   */
  window.safeRun = function safeRun(name, fn) {
    try {
      fn();
    } catch (e) {
      console.error('[BB SAFE FAIL]', name, e);
    }
  };

  /**
   * qs(selector) — querySelector with null guard.
   */
  window.bbQs = function bbQs(sel) {
    return document.querySelector(sel);
  };

  /**
   * bbOn(el, evt, fn) — addEventListener with null guard.
   */
  window.bbOn = function bbOn(el, evt, fn) {
    if (el) el.addEventListener(evt, fn);
  };
})();
