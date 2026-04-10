// Intentionally empty — this module previously housed the iter3.2
// selection diagnostic breadcrumbs (logSel / clearSelectionLog). The
// diagnostics were removed after the popover bug was fixed. The file
// itself is kept as a placeholder only because the sandboxed build
// environment could not physically delete it at cleanup time; it has
// no exports and no consumers. Safe to `rm` from a real shell.
export {};
