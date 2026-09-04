;;; .emacs --- MiladyOS MCP-enabled Emacs (both server + client), host-container port
;;;
;;; Adapted from miladyos-extra-deploys/deploy/gotty-dev/emacs-mcp-configmap.yaml
;;; for the host-mode miladyos container (--net=host).
;;;
;;;   * server:  emacs runs as a daemon (emacs --daemon) and registers MCP tools
;;;              under server-id "default" via mcp-server-lib (current API, stdio
;;;              transport). An MCP client drives it by spawning the library's
;;;              emacs-mcp-stdio.sh wrapper, which bridges stdio <-> emacsclient
;;;              <-> the daemon. => host-side milady can drive emacs.
;;;   * client:  emacs connects OUT to the local miladyos MCP at 127.0.0.1:6000/sse
;;;              (mcp.el) for a human in the gotty terminal to call miladyos tools.
;;;
;;; Tool handlers: input schema is auto-derived from the function arglist and a
;;; "MCP Parameters:" docstring section (args are strings, required unless
;;; &optional; &rest is rejected). Handlers are called positionally.

;; Bootstrap straight.el package manager
(defvar bootstrap-version)
(let ((bootstrap-file
       (expand-file-name "straight/repos/straight.el/bootstrap.el" user-emacs-directory))
      (bootstrap-version 6))
  (unless (file-exists-p bootstrap-file)
    (with-current-buffer
        (url-retrieve-synchronously
         "https://raw.githubusercontent.com/radian-software/straight.el/develop/install.el"
         'silent 'inhibit-cookies)
      (goto-char (point-max))
      (eval-print-last-sexp)))
  (load bootstrap-file nil 'nomessage))

(straight-use-package 'use-package)

;; Performance + terminal defaults
(setq gc-cons-threshold (* 50 1024 1024)
      read-process-output-max (* 1024 1024)
      inhibit-startup-message t)
(menu-bar-mode -1)
(when (fboundp 'tool-bar-mode) (tool-bar-mode -1))
(when (fboundp 'scroll-bar-mode) (scroll-bar-mode -1))

;;; ---- Emacs as MCP SERVER (mcp-server-lib, current API) ------------------
;;; Tools registered under server-id "default". Reachable via the stdio wrapper
;;; (emacs-mcp-stdio.sh) once this emacs runs as a server (daemon or
;;; M-x server-start).
(use-package mcp-server-lib
  :straight (mcp-server-lib :type git :host github :repo "laurynas-biveinis/mcp-server-lib.el")
  :config
  (defun milady-emacs-eval (code)
    "Evaluate Emacs Lisp CODE and return its printed value.

MCP Parameters:
  code - Emacs Lisp expression to evaluate."
    (condition-case err
        (format "%s" (eval (car (read-from-string code))))
      (error (format "Error: %s" (error-message-string err)))))

  (defun milady-emacs-find-file (path)
    "Open the file at PATH in an Emacs buffer.

MCP Parameters:
  path - absolute file path to open."
    (condition-case err
        (progn (find-file path) (format "Opened file: %s" path))
      (error (format "Error: %s" (error-message-string err)))))

  (defun milady-emacs-buffer-content ()
    "Return the current buffer's contents as a string."
    (buffer-string))

  (defun milady-emacs-save-buffer ()
    "Save the current buffer to its file."
    (save-buffer)
    "Buffer saved")

  (mcp-server-lib-register-server
   :id "default"
   :name "MiladyOS Emacs"
   :version "1.0.0"
   :instructions "You are driving a live GNU Emacs. Prefer emacs-eval for
anything beyond file open/save/read: it can switch buffers, insert text, run
commands, manage windows, and inspect state."
   :tools
   (list
    (list #'milady-emacs-eval
          :id "emacs-eval"
          :description "Evaluate an Emacs Lisp expression")
    (list #'milady-emacs-find-file
          :id "emacs-find-file"
          :description "Open a file in an Emacs buffer")
    (list #'milady-emacs-buffer-content
          :id "emacs-buffer-content"
          :description "Return the current buffer's contents")
    (list #'milady-emacs-save-buffer
          :id "emacs-save-buffer"
          :description "Save the current buffer")))

  ;; A daemon (emacs --daemon) is what an MCP client drives; make it MCP-ready
  ;; on boot so the stdio wrapper works without a manual mcp-server-lib-start.
  (when (daemonp)
    (condition-case err
        (mcp-server-lib-start)
      (error (message "mcp-server-lib-start: %s" (error-message-string err))))))

;;; ---- Emacs as MCP CLIENT (connect out to the local miladyos server) -----
(use-package mcp
  :straight (mcp :type git :host github :repo "lizqwerscott/mcp.el")
  :config
  (setq mcp-hub-servers
        '(("miladyos" . (:url "http://127.0.0.1:6000/sse"
                        :type "sse"
                        :env nil))))
  (add-hook 'after-init-hook #'mcp-hub-start-all-server)
  :bind
  (("C-c m s" . mcp-hub-start-server)
   ("C-c m r" . mcp-hub-restart-server)
   ("C-c m l" . mcp-hub-list-servers)
   ("C-c m t" . mcp-call-tool)))

;;; ---- Helpers -------------------------------------------------------------
(defun miladyos-mcp-status ()
  "Check MiladyOS MCP client connection."
  (interactive)
  (message "MiladyOS MCP servers: %s" (mapcar #'car mcp-hub-servers)))

(defun miladyos-mcp-reconnect ()
  "Reconnect to the MiladyOS MCP server."
  (interactive)
  (mcp-hub-restart-server "miladyos")
  (message "Reconnecting to MiladyOS MCP server..."))

(global-set-key (kbd "C-c M-s") #'miladyos-mcp-status)
(global-set-key (kbd "C-c M-r") #'miladyos-mcp-reconnect)

(add-hook 'emacs-startup-hook
          (lambda ()
            (setq gc-cons-threshold (* 2 1024 1024))
            (message "MiladyOS Emacs MCP server (stdio, id default) + client ready")))

(when (not (display-graphic-p))
  (setq frame-background-mode 'dark))

;;; .emacs ends here
