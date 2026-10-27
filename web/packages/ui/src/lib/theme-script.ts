export const STORAGE_KEY = "qbrix:theme";

// inlined in <head> so a remembered choice is on <html> before first paint.
export const themeScript = `try{var t=localStorage.getItem("${STORAGE_KEY}");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}`;
