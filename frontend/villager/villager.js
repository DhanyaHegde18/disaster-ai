/* Villagers' warning page. Shows ONLY alerts the Gram Panchayat approved (from /public/status). */
"use strict";

const POLL_MS = 60_000;
const DEMO = new URLSearchParams(location.search).get("demo") === "true";

const T = {
  kn: {
    app: "ಊರಿನ ಎಚ್ಚರಿಕೆ",
    tagline: "ಪ್ರವಾಹ ಮತ್ತು ಭೂಕುಸಿತ ಮುನ್ನೆಚ್ಚರಿಕೆ",
    choose: "ನಿಮ್ಮ ಊರನ್ನು ಆಯ್ಕೆಮಾಡಿ",
    searchLabel: "ಊರಿನ ಹೆಸರು ಬರೆಯಿರಿ (ಇಂಗ್ಲಿಷ್ ಅಕ್ಷರಗಳಲ್ಲಿ)",
    orBrowse: "ಅಥವಾ ಜಿಲ್ಲೆ ಮತ್ತು ತಾಲ್ಲೂಕು ಆಯ್ಕೆಮಾಡಿ:",
    district: "ಜಿಲ್ಲೆ", taluk: "ತಾಲ್ಲೂಕು",
    pickDistrict: "ಜಿಲ್ಲೆ ಆಯ್ಕೆಮಾಡಿ", pickTaluk: "ತಾಲ್ಲೂಕು ಆಯ್ಕೆಮಾಡಿ",
    filterVillages: "ಈ ತಾಲ್ಲೂಕಿನಲ್ಲಿ ಊರು ಹುಡುಕಿ",
    noMatch: "ಈ ಹೆಸರಿನ ಊರು ಸಿಗಲಿಲ್ಲ. ಬೇರೆ ರೀತಿ ಬರೆದು ನೋಡಿ, ಅಥವಾ ಕೆಳಗೆ ಜಿಲ್ಲೆ ಮತ್ತು ತಾಲ್ಲೂಕು ಆಯ್ಕೆಮಾಡಿ.",
    talukWord: "ತಾಲ್ಲೂಕು",
    change: "ಊರು ಬದಲಿಸಿ",
    warnHead: "ಎಚ್ಚರಿಕೆ!",
    calmHead: "ಸದ್ಯ ಯಾವುದೇ ಎಚ್ಚರಿಕೆ ಇಲ್ಲ",
    calmText: "ಗ್ರಾಮ ಪಂಚಾಯಿತಿ ಎಚ್ಚರಿಕೆ ನೀಡಿದರೆ ಇಲ್ಲಿ ಕಾಣಿಸುತ್ತದೆ. ಈ ಪುಟ ಪ್ರತಿ ನಿಮಿಷ ತಾನಾಗಿ ಪರಿಶೀಲಿಸುತ್ತದೆ.",
    approvedBy: (who, when) => `${who} ಅವರು ${when} ರಂದು ಅನುಮೋದಿಸಿದ್ದಾರೆ`,
    speak: "ಓದಿ ಹೇಳಿ",
    soundOff: "ಎಚ್ಚರಿಕೆ ಶಬ್ದ ಆನ್ ಮಾಡಿ",
    soundOn: "ಎಚ್ಚರಿಕೆ ಶಬ್ದ ಆನ್ ಆಗಿದೆ",
    soundAgain: "ಶಬ್ದ ಮತ್ತೆ ಆನ್ ಮಾಡಿ",
    call: "112 ಗೆ ಕರೆ ಮಾಡಿ",
    recent: "ಕಳೆದ 7 ದಿನಗಳ ಎಚ್ಚರಿಕೆಗಳು",
    tipsTitle: "ಮಳೆಗಾಲದ ಸುರಕ್ಷತಾ ಸಲಹೆಗಳು",
    tips: [
      "ನದಿ, ಹಳ್ಳ ಅಥವಾ ಸೇತುವೆಯ ಮೇಲೆ ನೀರು ಹರಿಯುತ್ತಿದ್ದರೆ ದಾಟಬೇಡಿ.",
      "ಗುಡ್ಡದಲ್ಲಿ ಬಿರುಕು, ಮಣ್ಣು ಜಾರುವುದು ಅಥವಾ ಕೆಸರು ನೀರು ಹರಿಯುವುದು ಕಂಡರೆ ತಕ್ಷಣ ಆ ಜಾಗ ಬಿಡಿ.",
      "ಮೊಬೈಲ್ ಚಾರ್ಜ್ ಮಾಡಿಟ್ಟುಕೊಳ್ಳಿ. ಟಾರ್ಚ್, ಔಷಧಿ ಮತ್ತು ಮುಖ್ಯ ದಾಖಲೆಗಳನ್ನು ಸಿದ್ಧವಾಗಿಡಿ.",
      "ಗ್ರಾಮ ಪಂಚಾಯಿತಿ ಸೂಚಿಸಿದರೆ ತಡಮಾಡದೆ ಕಾಳಜಿ ಕೇಂದ್ರಕ್ಕೆ ತೆರಳಿ.",
    ],
    onlyApproved: "ನಿಮ್ಮ ಗ್ರಾಮ ಪಂಚಾಯಿತಿ ಅನುಮೋದಿಸಿದ ಎಚ್ಚರಿಕೆಗಳು ಮಾತ್ರ ಇಲ್ಲಿ ಕಾಣಿಸುತ್ತವೆ.",
    checked: (t) => `ಕೊನೆಯ ಪರಿಶೀಲನೆ: ${t}`,
    test: "ಪರೀಕ್ಷೆ – ನಿಜವಾದ ಎಚ್ಚರಿಕೆಯಲ್ಲ",
    demo: "ಡೆಮೊ ಮೋಡ್: ಪರೀಕ್ಷಾ ಎಚ್ಚರಿಕೆಗಳೂ ಕಾಣಿಸುತ್ತವೆ.",
    offline: "ಸಂಪರ್ಕ ಇಲ್ಲ. ಕೊನೆಯದಾಗಿ ಪಡೆದ ಮಾಹಿತಿ ತೋರಿಸಲಾಗುತ್ತಿದೆ.",
    noKnVoice: "ಈ ಫೋನಿನಲ್ಲಿ ಕನ್ನಡ ಧ್ವನಿ ಇಲ್ಲ. ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಓದಲಾಗುತ್ತಿದೆ.",
    notifTitle: "ಊರಿನ ಎಚ್ಚರಿಕೆ",
    langBtn: "English",
    reportTitle: "ನಿಮ್ಮ ಕುಟುಂಬದ ಸ್ಥಿತಿ ತಿಳಿಸಿ",
    reportWhy: "ನೀವು ಎಲ್ಲಿದ್ದೀರಿ ಎಂದು ಗ್ರಾಮ ಪಂಚಾಯಿತಿ ಮತ್ತು ಸಹಾಯ ಸಂಸ್ಥೆಗಳಿಗೆ ತಿಳಿಯುತ್ತದೆ. ಸಹಾಯ ಬೇಕಾದರೆ ಗ್ರಾಮ ಪಂಚಾಯಿತಿ ನಿಮ್ಮನ್ನು ಸಂಪರ್ಕಿಸುತ್ತದೆ.",
    reportSignIn: "ವರದಿ ಮಾಡಲು ನಿಮ್ಮ ಮೊಬೈಲ್ ಸಂಖ್ಯೆ",
    sendCode: "ಕೋಡ್ ಕಳುಹಿಸಿ",
    codeLabel: "6 ಅಂಕಿಯ ಕೋಡ್",
    signIn: "ಮುಂದುವರಿಸಿ",
    codeSent: (p, m) => `${p} ಗೆ ಕೋಡ್ ಕಳುಹಿಸಲಾಗಿದೆ. ${m} ನಿಮಿಷ ಮಾನ್ಯ.`,
    demoCode: "ಡೆಮೊ (SMS ಇಲ್ಲ): ನಿಮ್ಮ ಕೋಡ್",
    howMany: "ಪ್ರತಿ ಸ್ಥಳದಲ್ಲಿ ಎಷ್ಟು ಜನ ಇದ್ದಾರೆ?",
    cats: { at_shelter: "ಕಾಳಜಿ ಕೇಂದ್ರದಲ್ಲಿ", with_relatives: "ಸಂಬಂಧಿಕರ ಮನೆ / ಬೇರೆ ಊರಿನಲ್ಲಿ",
            at_home: "ಮನೆಯಲ್ಲೇ ಇದ್ದಾರೆ", unknown: "ಎಲ್ಲಿದ್ದಾರೆ ಗೊತ್ತಿಲ್ಲ" },
    needsTitle: "ಏನಾದರೂ ಬೇಕೇ?",
    needs: { rescue: "ತುರ್ತು ರಕ್ಷಣೆ ಬೇಕು", food: "ಆಹಾರ", water: "ಕುಡಿಯುವ ನೀರು", medicine: "ಔಷಧಿ",
             elderly_help: "ಹಿರಿಯರು / ಅಂಗವಿಕಲರಿಗೆ ಸಹಾಯ" },
    rescueNote: "ಜೀವಕ್ಕೆ ಅಪಾಯವಿದ್ದರೆ ಮೊದಲು 112 ಗೆ ಕರೆ ಮಾಡಿ.",
    sendStatus: "ಸ್ಥಿತಿ ಕಳುಹಿಸಿ",
    saved: "ಧನ್ಯವಾದ. ನಿಮ್ಮ ಸ್ಥಿತಿ ಕಳುಹಿಸಲಾಗಿದೆ.",
    lastReport: (t) => `ಕೊನೆಯ ವರದಿ: ${t}. ಬದಲಾದರೆ ಮತ್ತೆ ಕಳುಹಿಸಿ.`,
    atLeastOne: "ಕನಿಷ್ಠ ಒಬ್ಬರ ಸ್ಥಿತಿ ತಿಳಿಸಿ.",
    logout: "ಲಾಗ್ ಔಟ್",
    less: "ಕಡಿಮೆ", more: "ಹೆಚ್ಚು",
    shelterTitle: "ಹತ್ತಿರದ ಕಾಳಜಿ ಕೇಂದ್ರ",
    useLocation: "ನನ್ನ ಸ್ಥಳದಿಂದ ಅಳೆಯಿರಿ",
    fromVillage: "ದೂರವನ್ನು ಊರಿನ ಮಧ್ಯದಿಂದ ಅಳೆಯಲಾಗಿದೆ (ನೇರ ದೂರ, ರಸ್ತೆ ಇನ್ನೂ ಉದ್ದ).",
    fromMe: "ದೂರವನ್ನು ನಿಮ್ಮ ಸ್ಥಳದಿಂದ ಅಳೆಯಲಾಗಿದೆ (ನೇರ ದೂರ, ರಸ್ತೆ ಇನ್ನೂ ಉದ್ದ).",
    locating: "ನಿಮ್ಮ ಸ್ಥಳ ಹುಡುಕಲಾಗುತ್ತಿದೆ…",
    locFail: "ನಿಮ್ಮ ಸ್ಥಳ ಸಿಗಲಿಲ್ಲ. ಊರಿನ ಮಧ್ಯದಿಂದ ದೂರ ತೋರಿಸಲಾಗಿದೆ.",
    km: (d) => `${d} ಕಿ.ಮೀ`,
    st: { open: "ತೆರೆದಿದೆ", full: "ತುಂಬಿದೆ", closed: "ಇನ್ನೂ ತೆರೆದಿಲ್ಲ" },
    spaces: (n) => `${n} ಜನರಿಗೆ ಸ್ಥಳವಿದೆ`,
    noneOpen: "ಸದ್ಯ ಯಾವ ಕಾಳಜಿ ಕೇಂದ್ರವೂ ತೆರೆದಿಲ್ಲ. ಗ್ರಾಮ ಪಂಚಾಯಿತಿ ತೆರೆದಾಗ ಇಲ್ಲಿ ಕಾಣಿಸುತ್ತದೆ. ಅಪಾಯವಿದ್ದರೆ ಎತ್ತರದ ಸುರಕ್ಷಿತ ಸ್ಥಳಕ್ಕೆ ಹೋಗಿ, 112 ಗೆ ಕರೆ ಮಾಡಿ.",
    directions: "ದಾರಿ ತೋರಿಸಿ",
    showRoute: "ನಕ್ಷೆಯಲ್ಲಿ ದಾರಿ ನೋಡಿ",
    offlineBanner: "ಸಂಪರ್ಕ ಇಲ್ಲ. ಕೊನೆಯದಾಗಿ ಪಡೆದ ಮಾಹಿತಿ ತೋರಿಸಲಾಗುತ್ತಿದೆ.",
    outboxWaiting: (when) => `ನಿಮ್ಮ ವರದಿ (${when}) ಫೋನಿನಲ್ಲಿ ಉಳಿಸಲಾಗಿದೆ. ಸಂಪರ್ಕ ಸಿಕ್ಕ ತಕ್ಷಣ ತಾನಾಗಿ ಕಳುಹಿಸಲಾಗುತ್ತದೆ.`,
    outboxRescue: "ಜೀವಕ್ಕೆ ಅಪಾಯವಿದ್ದರೆ ಕಾಯಬೇಡಿ: 112 ಗೆ ಕರೆ ಮಾಡಿ ಅಥವಾ SMS ಮೂಲಕ ಸಹಾಯ ಕೇಳಿ.",
    outboxSent: "ಉಳಿಸಿದ ವರದಿ ಈಗ ಕಳುಹಿಸಲಾಗಿದೆ.",
    outboxSignIn: "ಉಳಿಸಿದ ವರದಿ ಕಳುಹಿಸಲು ಮತ್ತೆ ಮೊಬೈಲ್ ಸಂಖ್ಯೆಯಿಂದ ಪ್ರವೇಶಿಸಿ.",
    savedOffline: "ಸಂಪರ್ಕ ಇಲ್ಲ. ವರದಿ ಫೋನಿನಲ್ಲಿ ಉಳಿಸಲಾಗಿದೆ, ಸಂಪರ್ಕ ಸಿಕ್ಕಾಗ ತಾನಾಗಿ ಕಳುಹಿಸಲಾಗುತ್ತದೆ.",
    smsSos: "SMS ಮೂಲಕ ಸಹಾಯ ಕೇಳಿ",
    smsHint: "ಇಂಟರ್ನೆಟ್ ಇಲ್ಲದಿದ್ದರೂ SMS ಹೋಗುತ್ತದೆ. ಸಂದೇಶ ಸಿದ್ಧವಾಗಿರುತ್ತದೆ; ಗ್ರಾಮ ಪಂಚಾಯಿತಿ ಸದಸ್ಯರು ಅಥವಾ ಸಂಬಂಧಿಕರ ಸಂಖ್ಯೆ ಆಯ್ಕೆಮಾಡಿ ಕಳುಹಿಸಿ.",
    smsBody: (place, people, unknown, loc) => `SOS: ತುರ್ತು ರಕ್ಷಣೆ ಬೇಕು. ಊರು: ${place}.` +
      (people ? ` ಜನ: ${people}.` : "") + (unknown ? ` ಎಲ್ಲಿದ್ದಾರೆ ಗೊತ್ತಿಲ್ಲ: ${unknown}.` : "") + (loc ? ` ಸ್ಥಳ: ${loc}` : ""),
    install: "ಫೋನಿಗೆ ಆ್ಯಪ್ ಆಗಿ ಸೇರಿಸಿ",
    routeLoading: "ದಾರಿ ಹುಡುಕಲಾಗುತ್ತಿದೆ…",
    routeTo: (name) => `${name} ಗೆ ದಾರಿ`,
    routeInfo: (km, min) => `ರಸ್ತೆಯಲ್ಲಿ ${km} ಕಿ.ಮೀ · ನಡೆದರೆ ಸುಮಾರು ${min} ನಿಮಿಷ`,
    routeNone: "ರಸ್ತೆ ದಾರಿ ಸಿಗಲಿಲ್ಲ. ಗೆರೆಯು ಕೇಂದ್ರದ ದಿಕ್ಕನ್ನು ಮಾತ್ರ ತೋರಿಸುತ್ತದೆ. \"ದಾರಿ ತೋರಿಸಿ\" ಒತ್ತಿ Google Maps ನಲ್ಲಿ ನೋಡಿ.",
    routeFromMe: "ನೀವು ಇರುವ ಸ್ಥಳದಿಂದ",
    routeFromVillage: "ಊರಿನ ಮಧ್ಯದಿಂದ (ನಿಮ್ಮ ಸ್ಥಳ ಸಿಗಲಿಲ್ಲ)",
    routeSafety: "ಈ ದಾರಿಗೆ ಪ್ರವಾಹ ಅಥವಾ ಭೂಕುಸಿತದ ಮಾಹಿತಿ ಇಲ್ಲ. ನೀರು ಹರಿಯುವ ರಸ್ತೆ, ಸೇತುವೆ ಮತ್ತು ಗುಡ್ಡದ ಬದಿ ತಪ್ಪಿಸಿ; ಊರಿನವರು ಹೇಳುವ ಸುರಕ್ಷಿತ ದಾರಿ ಬಳಸಿ.",
    youHere: "ನೀವು", villageHere: "ಊರು",
    mapOffline: "ನಕ್ಷೆ ತೆರೆಯಲು ಇಂಟರ್ನೆಟ್ ಬೇಕು. \"ದಾರಿ ತೋರಿಸಿ\" ಬಳಸಿ.",
    callCentre: "ಕೇಂದ್ರಕ್ಕೆ ಕರೆ",
    err: { 400: "ಸರಿಯಾದ 10 ಅಂಕಿಯ ಮೊಬೈಲ್ ಸಂಖ್ಯೆ ನಮೂದಿಸಿ.", 401: "ಕೋಡ್ ತಪ್ಪಾಗಿದೆ ಅಥವಾ ಅವಧಿ ಮುಗಿದಿದೆ.",
           429: "ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.", 502: "SMS ಕಳುಹಿಸಲು ಆಗಲಿಲ್ಲ. ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಪ್ರಯತ್ನಿಸಿ." },
  },
  en: {
    app: "Village Alert",
    tagline: "Flood and landslide warnings",
    choose: "Choose your village",
    searchLabel: "Type your village's name",
    orBrowse: "Or choose your district and taluk:",
    district: "District", taluk: "Taluk",
    pickDistrict: "Choose district", pickTaluk: "Choose taluk",
    filterVillages: "Find a village in this taluk",
    noMatch: "No village with that name. Try another spelling, or choose your district and taluk below.",
    talukWord: "taluk",
    change: "Change village",
    warnHead: "Warning!",
    calmHead: "No warnings right now",
    calmText: "If your Gram Panchayat issues a warning, it will appear here. This page checks by itself every minute.",
    approvedBy: (who, when) => `Approved by ${who} on ${when}`,
    speak: "Read aloud",
    soundOff: "Turn on alarm sound",
    soundOn: "Alarm sound is on",
    soundAgain: "Turn sound on again",
    call: "Call 112",
    recent: "Warnings in the last 7 days",
    tipsTitle: "Monsoon safety tips",
    tips: [
      "Do not cross a river, stream or bridge when water is flowing over it.",
      "If you see cracks on a hillside, soil slipping or muddy water flowing, leave that place at once.",
      "Keep your phone charged. Keep a torch, medicines and important documents ready.",
      "If the Gram Panchayat asks, go to the relief centre (ಕಾಳಜಿ ಕೇಂದ್ರ) without delay.",
    ],
    onlyApproved: "Only warnings approved by your Gram Panchayat appear here.",
    checked: (t) => `Last checked: ${t}`,
    test: "TEST – not a real warning",
    demo: "Demo mode: test warnings are shown too.",
    offline: "No connection. Showing the last information received.",
    noKnVoice: "No Kannada voice on this phone. Reading in English.",
    notifTitle: "Village Alert",
    langBtn: "ಕನ್ನಡ",
    reportTitle: "Tell us your family's status",
    reportWhy: "Your Gram Panchayat and relief organisations will know where you are. If you need help, the Gram Panchayat will contact you.",
    reportSignIn: "Your mobile number, to send a report",
    sendCode: "Send code",
    codeLabel: "6-digit code",
    signIn: "Continue",
    codeSent: (p, m) => `Code sent to ${p}. It works for ${m} minutes.`,
    demoCode: "Demo (no SMS): your code is",
    howMany: "How many people are in each place?",
    cats: { at_shelter: "At the relief centre", with_relatives: "With relatives / in another village",
            at_home: "Staying at home", unknown: "Don't know where they are" },
    needsTitle: "Do you need anything?",
    needs: { rescue: "Urgent rescue needed", food: "Food", water: "Drinking water", medicine: "Medicine",
             elderly_help: "Help for elderly / disabled" },
    rescueNote: "If someone's life is in danger, call 112 first.",
    sendStatus: "Send status",
    saved: "Thank you. Your status has been sent.",
    lastReport: (t) => `Last report: ${t}. Send again if anything changes.`,
    atLeastOne: "Report at least one person.",
    logout: "Log out",
    less: "Fewer", more: "More",
    shelterTitle: "Nearest relief centre",
    useLocation: "Measure from where I am",
    fromVillage: "Distance from the village centre (straight line; the road is longer).",
    fromMe: "Distance from where you are (straight line; the road is longer).",
    locating: "Finding your location…",
    locFail: "Could not get your location. Showing distance from the village centre.",
    km: (d) => `${d} km`,
    st: { open: "Open", full: "Full", closed: "Not open yet" },
    spaces: (n) => `Room for ${n} more`,
    noneOpen: "No relief centre is open right now. It will appear here when the Gram Panchayat opens one. If you are in danger, move to high, safe ground and call 112.",
    directions: "Directions",
    showRoute: "See route on map",
    offlineBanner: "No connection. Showing the last information received.",
    outboxWaiting: (when) => `Your report (${when}) is saved on this phone. It will be sent by itself as soon as there is a connection.`,
    outboxRescue: "If a life is in danger, don't wait: call 112 or ask for help by SMS.",
    outboxSent: "Your saved report has now been sent.",
    outboxSignIn: "To send your saved report, sign in again with your mobile number.",
    savedOffline: "No connection. Your report is saved on this phone and will be sent by itself when there is a connection.",
    smsSos: "Ask for help by SMS",
    smsHint: "SMS works without internet. The message is ready; choose a Gram Panchayat member or a relative and send it.",
    smsBody: (place, people, unknown, loc) => `SOS: Need urgent rescue. Village: ${place}.` +
      (people ? ` People: ${people}.` : "") + (unknown ? ` Missing: ${unknown}.` : "") + (loc ? ` Location: ${loc}` : ""),
    install: "Add as an app on this phone",
    routeLoading: "Finding the route…",
    routeTo: (name) => `Route to ${name}`,
    routeInfo: (km, min) => `${km} km by road · about ${min} min on foot`,
    routeNone: "Couldn't find a road route. The line only shows the direction of the centre. Tap \"Directions\" to use Google Maps.",
    routeFromMe: "From where you are",
    routeFromVillage: "From the village centre (your location wasn't available)",
    routeSafety: "This route knows nothing about floods or landslides. Avoid flooded roads, bridges and hillsides; use the safe way local people tell you.",
    youHere: "You", villageHere: "Village",
    mapOffline: "The map needs internet. Use \"Directions\" instead.",
    callCentre: "Call centre",
    err: {},
  },
};

const S = {
  lang: "kn", village: null, data: null, districts: [], talukVillages: [], searchHits: null,
  seen: null, sound: false, audio: null,
  centres: null, loc: null,        // loc = {lat, lon} only after the person taps "measure from where I am"
};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const t = (k) => T[S.lang][k];
const fmt = (iso) => new Date(iso).toLocaleString(S.lang === "kn" ? "kn-IN" : "en-IN",
  { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

function store(k, v) { try { localStorage.setItem(k, v); } catch { } }
function load(k) { try { return localStorage.getItem(k); } catch { return null; } }

function toast(msg) {
  const el = $("toast"); el.textContent = msg; el.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (el.hidden = true), 4000);
}

// ---------- language ----------
function applyLang() {
  document.documentElement.lang = S.lang;
  document.title = t("app");
  document.querySelectorAll("[data-t]").forEach((el) => {
    const v = T[S.lang][el.dataset.t];
    if (typeof v === "string") el.textContent = v;
  });
  $("btn-lang").textContent = t("langBtn");
  $("tips").innerHTML = t("tips").map((x) => `<li>${esc(x)}</li>`).join("");
  setSoundButton();
  renderPicker();
  renderReportForm();
  if (S.data) renderStatus();
  if (S.centres) renderCentres();
  renderOutbox();
}

$("btn-lang").addEventListener("click", () => {
  S.lang = S.lang === "kn" ? "en" : "kn";
  store("v-lang", S.lang);
  applyLang();
});

// ---------- village choice: search the whole state, or district -> taluk -> village ----------
const districtName = (d) => S.lang === "kn" ? (d.name_kn || d.name) : d.name;

function villageButtons(list, withPlace) {
  return list.map((v) => `
    <button type="button" data-id="${esc(v.village_id)}">
      <b>${esc(S.lang === "kn" ? (v.name_kn || v.name) : v.name)}</b>
      <span>${withPlace ? `${esc(v.taluk)} · ${esc(districtName(S.districts.find((d) => d.name === v.district) || { name: v.district }))}` : ""}</span>
    </button>`).join("");
}

function bindVillageButtons(box) {
  box.querySelectorAll("button[data-id]").forEach((b) => b.addEventListener("click", () => chooseVillage(b.dataset.id)));
}

function renderPicker() {
  const ds = $("pick-district"), current = ds.value;
  ds.innerHTML = `<option value="">${esc(t("pickDistrict"))}</option>` +
    S.districts.map((d) => `<option value="${esc(d.name)}">${esc(districtName(d))}</option>`).join("");
  ds.value = current;
  renderTaluks();
  $("v-filter").placeholder = t("filterVillages");
  renderSearchHits();
  renderTalukVillages();
}

function renderTaluks() {
  const d = S.districts.find((x) => x.name === $("pick-district").value);
  const ts = $("pick-taluk"), current = ts.value;
  ts.disabled = !d;
  ts.innerHTML = `<option value="">${esc(t("pickTaluk"))}</option>` +
    (d ? d.taluks.map((x) => `<option value="${esc(x.taluk_id)}">${esc(x.name)}</option>`).join("") : "");
  if (d && d.taluks.some((x) => x.taluk_id === current)) ts.value = current;
}

function renderSearchHits() {
  const box = $("search-results");
  if (S.searchHits === null) { box.innerHTML = ""; return; }
  box.innerHTML = S.searchHits.length ? villageButtons(S.searchHits, true) : `<p class="hint">${esc(t("noMatch"))}</p>`;
  bindVillageButtons(box);
}

function renderTalukVillages() {
  const q = $("v-filter").value.trim().toLowerCase();
  const list = S.talukVillages.filter((v) => !q || v.name.toLowerCase().includes(q));
  $("v-filter").hidden = !S.talukVillages.length;
  $("village-buttons").innerHTML = villageButtons(list, false);
  bindVillageButtons($("village-buttons"));
}

let searchTimer = null;
$("v-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = $("v-search").value.trim();
  if (q.length < 2) { S.searchHits = null; renderSearchHits(); return; }
  searchTimer = setTimeout(async () => {
    try { S.searchHits = await (await fetch(`/public/villages?q=${encodeURIComponent(q)}&limit=12`)).json(); }
    catch { S.searchHits = []; }
    renderSearchHits();
  }, 250);
});
$("pick-district").addEventListener("change", () => { S.talukVillages = []; renderTaluks(); renderTalukVillages(); });
$("pick-taluk").addEventListener("change", async () => {
  const id = $("pick-taluk").value;
  S.talukVillages = [];
  if (id) {
    try { S.talukVillages = await (await fetch(`/public/villages?taluk_id=${encodeURIComponent(id)}&limit=600`)).json(); }
    catch { S.talukVillages = []; }
  }
  $("v-filter").value = "";
  renderTalukVillages();
});
$("v-filter").addEventListener("input", renderTalukVillages);

function chooseVillage(id) {
  S.village = id; S.seen = null; S.data = null; S.centres = null;
  store("v-village", id);
  showHome();
  refresh();
  initReport();
}

function showHome() {
  $("picker").hidden = !!S.village;
  $("home").hidden = !S.village;
}

$("btn-change").addEventListener("click", () => {
  S.village = null; store("v-village", "");
  showHome();
  window.scrollTo(0, 0);
});

// ---------- data ----------
async function refresh() {
  if (!S.village) return;
  try {
    const res = await fetch(`/public/status/${encodeURIComponent(S.village)}${DEMO ? "?demo=true" : ""}`);
    if (res.status === 404) { S.village = null; showHome(); return; }
    if (!res.ok) throw new Error(res.statusText);
    setOffline(res.headers.get("X-From-Cache") === "1" || !navigator.onLine);   // answered from the saved copy
    S.data = await res.json();
    store("v-last", JSON.stringify(S.data));      // shown if the network drops later
    renderStatus();
    checkNew();
    loadCentres();
  } catch {
    const cached = load("v-last");
    if (cached && !S.data) { S.data = JSON.parse(cached); renderStatus(); }
    const cachedCentres = load(`v-centres-${S.village}`);
    if (cachedCentres && !S.centres) { S.centres = JSON.parse(cachedCentres); renderCentres(); }
    setOffline(true);
  }
}

// ---------- nearest relief centres ----------
async function loadCentres() {
  const q = S.loc ? `?lat=${S.loc.lat.toFixed(4)}&lon=${S.loc.lon.toFixed(4)}` : "";
  try {
    const res = await fetch(`/public/shelters/${encodeURIComponent(S.village)}${q}`);
    if (!res.ok) throw new Error(res.statusText);
    S.centres = await res.json();
    if (!S.loc) store(`v-centres-${S.village}`, JSON.stringify(S.centres));   // kept for when the network drops
    renderCentres();
  } catch { /* keep what is shown */ }
}

function renderCentres() {
  const c = S.centres, list = c ? c.shelters.slice(0, 2) : [];
  $("centres").hidden = !list.length;
  $("centres").classList.toggle("urgent", !!(S.data && S.data.active.length));   // stands out during a warning
  if (!list.length) return;
  $("centres-from").textContent = c.measured_from === "your_location" ? t("fromMe") : t("fromVillage");
  $("none-open").hidden = c.any_open;
  const kn = S.lang === "kn";
  $("centre-list").innerHTML = list.map((s) => {
    const name = kn ? (s.name_kn || s.name) : s.name;
    const meta = [t("km")(s.distance_km), s.status === "open" ? t("spaces")(s.spaces_left) : ""].filter(Boolean).join(" · ");
    const maps = `https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lon}`;
    return `<article class="centre ${s.status}">
      <div class="c-head"><b lang="${S.lang}">${esc(name)}</b><span class="c-status">${esc(t("st")[s.status])}</span></div>
      <p class="c-meta">${esc(meta)}</p>
      <div class="c-actions">
        <a class="big ${s.status === "open" ? "primary" : "secondary"}" href="${maps}" target="_blank" rel="noopener">${esc(t("directions"))}</a>
        <button class="big secondary" type="button" data-route="${esc(s.shelter_id)}">${esc(t("showRoute"))}</button>
        ${s.phone ? `<a class="big secondary" href="tel:${esc(s.phone)}">${esc(t("callCentre"))}</a>` : ""}
      </div>
    </article>`;
  }).join("");
  $("centre-list").querySelectorAll("[data-route]").forEach((b) => b.addEventListener("click", () =>
    showRoute(list.find((s) => s.shelter_id === b.dataset.route))));
}

// ---------- route on a map: from the phone's location (or the village centre) to a centre ----------
// The map library is downloaded only when someone asks for a route, to keep the page light.
// Walking route by road from the free OpenStreetMap routing service used by openstreetmap.org.
const ROUTE_URL = "https://routing.openstreetmap.de/routed-foot/route/v1/foot/";
let routeMap = null, routeLayer = null, leafletLoading = null;

function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (leafletLoading) return leafletLoading;
  leafletLoading = new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet"; css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(css);
    const js = document.createElement("script");
    js.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    js.onload = () => resolve();
    js.onerror = () => { leafletLoading = null; reject(new Error("map library unavailable")); };
    document.head.appendChild(js);
  });
  return leafletLoading;
}

function myLocation() {
  // Phones only share location on https pages (or on the laptop itself as localhost).
  if (S.loc) return Promise.resolve(S.loc);
  if (!("geolocation" in navigator) || !window.isSecureContext) return Promise.resolve(null);
  return new Promise((resolve) => navigator.geolocation.getCurrentPosition(
    (pos) => { S.loc = { lat: pos.coords.latitude, lon: pos.coords.longitude }; resolve(S.loc); },
    () => resolve(null), { enableHighAccuracy: true, timeout: 10000, maximumAge: 120000 }));
}

async function roadRoute(from, to) {
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 12000);
  try {
    const res = await fetch(`${ROUTE_URL}${from.lon},${from.lat};${to.lon},${to.lat}?overview=full&geometries=geojson`,
                            { signal: ctl.signal });
    if (!res.ok) return null;
    const r = (await res.json()).routes?.[0];
    if (!r) return null;
    return { line: r.geometry.coordinates.map(([lon, lat]) => [lat, lon]), km: r.distance / 1000, min: r.duration / 60 };
  } catch { return null; } finally { clearTimeout(timer); }
}

async function showRoute(s) {
  if (!s) return;
  const box = $("route-box"), info = $("route-info");
  const name = S.lang === "kn" ? (s.name_kn || s.name) : s.name;
  box.hidden = false;
  $("route-title").textContent = t("routeTo")(name);
  info.textContent = t("routeLoading");
  box.scrollIntoView({ behavior: "smooth", block: "start" });
  try { await loadLeaflet(); } catch { info.textContent = t("mapOffline"); return; }

  const me = await myLocation();
  const v = S.data && S.data.village;
  const from = me || (v ? { lat: v.lat, lon: v.lon } : null);
  if (!from) { info.textContent = t("routeNone"); return; }
  if (!routeMap) {
    routeMap = L.map("route-map", { scrollWheelZoom: false });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                { maxZoom: 18, attribution: "&copy; OpenStreetMap contributors" }).addTo(routeMap);
    routeLayer = L.layerGroup().addTo(routeMap);
  }
  routeLayer.clearLayers();
  const css = getComputedStyle(document.documentElement);
  const brand = css.getPropertyValue("--brand").trim(), calm = css.getPropertyValue("--calm").trim();
  L.circleMarker([from.lat, from.lon], { radius: 9, color: "#fff", weight: 3, fillColor: brand, fillOpacity: 1 })
    .bindTooltip(me ? t("youHere") : t("villageHere"), { permanent: true, direction: "top", offset: [0, -8] }).addTo(routeLayer);
  L.marker([s.lat, s.lon], { icon: L.divIcon({ className: "", html: `<span class="centre-pin"></span>`, iconSize: [22, 22], iconAnchor: [11, 11] }) })
    .bindTooltip(name.length > 26 ? name.slice(0, 25) + "…" : name, { permanent: true, direction: "top", offset: [0, -10] })
    .addTo(routeLayer);

  const route = await roadRoute(from, s);
  const line = route ? route.line : [[from.lat, from.lon], [s.lat, s.lon]];
  L.polyline(line, route ? { color: brand, weight: 6, opacity: 0.85 } : { color: calm, weight: 4, dashArray: "8 8" }).addTo(routeLayer);
  routeMap.invalidateSize();
  routeMap.fitBounds(L.latLngBounds(line), { padding: [36, 36], maxZoom: 16 });
  const where = me ? t("routeFromMe") : t("routeFromVillage");
  info.textContent = route
    ? `${where}: ${t("routeInfo")(route.km.toFixed(1), Math.max(1, Math.round(route.min)))}`
    : `${where}. ${t("routeNone")}`;
}

$("btn-locate").addEventListener("click", () => {
  // Phones only share location on https pages (or on the laptop itself as localhost).
  if (!("geolocation" in navigator) || !window.isSecureContext) { toast(t("locFail")); return; }
  toast(t("locating"));
  navigator.geolocation.getCurrentPosition(
    (pos) => { S.loc = { lat: pos.coords.latitude, lon: pos.coords.longitude }; loadCentres(); },
    () => toast(t("locFail")),
    { enableHighAccuracy: false, timeout: 15000, maximumAge: 300000 });
});

// ---------- rendering ----------
const WARN_ICON = `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2 1 21h22L12 2zm0 6 .01 0c.55 0 1 .45 1 1v5a1 1 0 1 1-2 0V9c0-.55.45-1 1-1zm0 9.5a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 0 1 0-2.5z"/></svg>`;

function message(a) { return S.lang === "kn" ? a.message_kn : a.message_en; }

function renderStatus() {
  const d = S.data;
  const v = d.village;
  $("place-name").textContent = S.lang === "kn" ? (v.name_kn || v.name) : v.name;
  $("place-sub").textContent = `${v.taluk} ${t("talukWord")}, ${S.lang === "kn" ? (v.district_kn || v.district) : v.district}`;
  $("call").href = `tel:${d.emergency_number || "112"}`;

  if (d.active.length) {
    $("status").innerHTML = d.active.map((a) => `
      <article class="card warn${a.test ? " test" : ""}">
        ${a.test ? `<span class="testtag">${t("test")}</span>` : ""}
        <div class="head">${WARN_ICON}<span>${t("warnHead")}</span></div>
        <p class="msg" lang="${S.lang}">${esc(message(a))}</p>
        <p class="who">${esc(t("approvedBy")(a.approved_by, fmt(a.approved_at)))}</p>
        <button class="speak" type="button" data-id="${a.id}">🔊 ${t("speak")}</button>
      </article>`).join("");
    $("status").querySelectorAll(".speak").forEach((b) =>
      b.addEventListener("click", () => speak(d.active.find((a) => String(a.id) === b.dataset.id))));
  } else {
    $("status").innerHTML = `<article class="card calm"><div class="head">${t("calmHead")}</div><p>${t("calmText")}</p></article>`;
  }

  $("centres").classList.toggle("urgent", !!d.active.length);
  $("recent-wrap").hidden = !d.recent.length;
  $("recent").innerHTML = d.recent.map((a) => `
    <div class="past">${a.test ? `<span class="testtag">${t("test")}</span>` : ""}
      <p lang="${S.lang}">${esc(message(a))}</p>
      <p class="when">${esc(t("approvedBy")(a.approved_by, fmt(a.approved_at)))}</p></div>`).join("");
  $("checked").textContent = t("checked")(fmt(d.checked_at));
}

// ---------- new warning: siren, vibration, notification ----------
function checkNew() {
  const ids = new Set(S.data.active.map((a) => a.id));
  if (S.seen === null) { S.seen = ids; return; }          // first load of this village: no siren
  const fresh = S.data.active.filter((a) => !S.seen.has(a.id));
  S.seen = ids;
  if (!fresh.length) return;
  if (S.sound) playSiren();
  if (navigator.vibrate) navigator.vibrate([600, 300, 600, 300, 600]);
  if (S.sound && "Notification" in window && Notification.permission === "granted") {
    new Notification(t("notifTitle"), { body: message(fresh[0]), tag: "village-alert", requireInteraction: true });
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function playSiren() {
  if (!S.audio) return;
  const ctx = S.audio;
  if (ctx.state === "suspended") ctx.resume();
  const t0 = ctx.currentTime + 0.05, osc = ctx.createOscillator(), g = ctx.createGain();
  osc.type = "square";
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(0.2, t0 + 0.05);
  for (let i = 0; i < 4; i++) {
    const s = t0 + i * 0.8;
    osc.frequency.setValueAtTime(650, s);
    osc.frequency.linearRampToValueAtTime(1100, s + 0.4);
    osc.frequency.linearRampToValueAtTime(650, s + 0.8);
  }
  g.gain.setValueAtTime(0.2, t0 + 3.1);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + 3.25);
  osc.connect(g).connect(ctx.destination);
  osc.start(t0); osc.stop(t0 + 3.3);
}

function setSoundButton() {
  const b = $("btn-sound");
  b.setAttribute("aria-pressed", String(S.sound));
  b.textContent = S.sound ? t("soundOn") : (load("v-sound") === "on" ? t("soundAgain") : t("soundOff"));
}

$("btn-sound").addEventListener("click", async () => {
  if (S.sound) { S.sound = false; store("v-sound", "off"); setSoundButton(); return; }
  S.audio = S.audio || new (window.AudioContext || window.webkitAudioContext)();   // needs this tap
  await S.audio.resume();
  S.sound = true; store("v-sound", "on"); setSoundButton();
  if ("Notification" in window && Notification.permission === "default") {
    try { await Notification.requestPermission(); } catch { }
  }
});

// ---------- read aloud ----------
function speak(a) {
  if (!a || !("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const voices = speechSynthesis.getVoices();
  let text = message(a), lang = S.lang === "kn" ? "kn-IN" : "en-IN";
  let voice = voices.find((v) => v.lang.toLowerCase().startsWith(S.lang));
  if (S.lang === "kn" && !voice) {            // many phones have no Kannada voice
    toast(t("noKnVoice"));
    text = a.message_en; lang = "en-IN";
    voice = voices.find((v) => v.lang === "en-IN") || voices.find((v) => v.lang.startsWith("en"));
  }
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang; if (voice) u.voice = voice; u.rate = 0.9;
  speechSynthesis.speak(u);
}
if ("speechSynthesis" in window) speechSynthesis.getVoices();   // some browsers load voices lazily

// ---------- family status report (needs a villager sign-in) ----------
const CATS = ["at_shelter", "with_relatives", "at_home", "unknown"];
const NEED_CODES = ["rescue", "food", "water", "medicine", "elderly_help"];
const R = { counts: { at_shelter: 0, with_relatives: 0, at_home: 0, unknown: 0 }, needs: new Set(), last: null };

async function call(path, body) {
  const res = await fetch(path, { method: body ? "POST" : "GET", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await res.json(); } catch { }
  if (!res.ok) {
    const detail = data && typeof data.detail === "string" ? data.detail : res.statusText;
    const err = new Error(T[S.lang].err[res.status] || detail);
    err.status = res.status;
    throw err;
  }
  return data;
}

function reportError(msg) { $("r-error").textContent = msg || ""; $("r-error").hidden = !msg; }

function showReportStep(step) {      // "phone" | "code" | "form"
  $("r-phone-form").hidden = step !== "phone";
  $("r-code-form").hidden = step !== "code";
  $("r-form").hidden = step !== "form";
}

function renderReportForm() {
  $("steppers").innerHTML = CATS.map((c) => `
    <div class="stepper">
      <span>${esc(t("cats")[c])}</span>
      <div class="ctl">
        <button type="button" data-cat="${c}" data-d="-1" aria-label="${esc(t("less"))}: ${esc(t("cats")[c])}">−</button>
        <output id="n-${c}" aria-live="polite">${R.counts[c]}</output>
        <button type="button" data-cat="${c}" data-d="1" aria-label="${esc(t("more"))}: ${esc(t("cats")[c])}">+</button>
      </div>
    </div>`).join("");
  $("steppers").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    const c = b.dataset.cat;
    R.counts[c] = Math.max(0, Math.min(50, R.counts[c] + Number(b.dataset.d)));
    $(`n-${c}`).textContent = R.counts[c];
  }));
  $("needs").innerHTML = NEED_CODES.map((n) => `
    <label class="need-opt ${n}"><input type="checkbox" value="${n}" ${R.needs.has(n) ? "checked" : ""}>
      <span>${esc(t("needs")[n])}</span></label>`).join("");
  $("needs").querySelectorAll("input").forEach((i) => i.addEventListener("change", () => {
    i.checked ? R.needs.add(i.value) : R.needs.delete(i.value);
  }));
  $("r-last").textContent = R.last ? t("lastReport")(fmt(R.last)) : "";
}

function loadReport(rep) {
  if (!rep) return;
  CATS.forEach((c) => (R.counts[c] = rep[c] || 0));
  R.needs = new Set(rep.needs || []);
  R.last = rep.reported_at;
}

async function initReport() {
  reportError("");
  try {
    const me = await call("/public/me");
    store("v-signed-in", "1");
    loadReport(me.report);
    renderReportForm();
    showReportStep("form");
  } catch (err) {
    if (!err.status && load("v-signed-in") === "1") {      // no network, but signed in earlier: allow a report
      renderReportForm();
      showReportStep("form");
      return;
    }
    if (err.status === 401) store("v-signed-in", "0");
    showReportStep("phone");
  }
}

$("r-phone-form").addEventListener("submit", async (e) => {
  e.preventDefault(); reportError("");
  try {
    const r = await call("/public/auth/request-code", { phone: $("r-phone").value });
    $("r-sent").textContent = t("codeSent")(r.phone, r.expires_in_min);
    $("r-demo").hidden = !r.demo_code;
    if (r.demo_code) $("r-demo").innerHTML = `${esc(t("demoCode"))} <b>${esc(r.demo_code)}</b>`;
    $("r-code").value = "";
    showReportStep("code");
    $("r-code").focus();
  } catch (err) { reportError(err.message); }
});

$("r-code-form").addEventListener("submit", async (e) => {
  e.preventDefault(); reportError("");
  try {
    await call("/public/auth/verify", { phone: $("r-phone").value, code: $("r-code").value, village_id: S.village });
    store("v-signed-in", "1");
    await initReport();
    flushOutbox();
  } catch (err) { reportError(err.message); }
});

$("r-form").addEventListener("submit", async (e) => {
  e.preventDefault(); reportError("");
  if (CATS.every((c) => R.counts[c] === 0)) { reportError(t("atLeastOne")); return; }
  const body = { village_id: S.village, ...R.counts, needs: [...R.needs] };
  try {
    const r = await call("/public/report", body);
    R.last = r.report.reported_at;
    $("r-last").textContent = t("lastReport")(fmt(R.last));
    await outbox("del");                                    // a newer report replaces any saved one
    renderOutbox();
    toast(t("saved"));
  } catch (err) {
    if (!err.status) {                                      // no network: keep it on the phone, send later
      await queueReport(body);
      toast(t("savedOffline"));
      return;
    }
    if (err.status === 401) { store("v-signed-in", "0"); showReportStep("phone"); }
    reportError(err.message);
  }
});

// ---------- offline: saved reports, sent when signal returns ----------
function idb() {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open("village-alert", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("outbox");
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

async function outbox(mode, value) {
  if (!("indexedDB" in window)) {                           // very old browser: fall back to localStorage
    if (mode === "get") { const v = load("v-outbox"); return v ? JSON.parse(v) : undefined; }
    store("v-outbox", mode === "del" ? "" : JSON.stringify(value));
    return;
  }
  try {
    const d = await idb();
    return await new Promise((resolve, reject) => {
      const tx = d.transaction("outbox", mode === "get" ? "readonly" : "readwrite");
      const st = tx.objectStore("outbox");
      const r = mode === "get" ? st.get("report") : mode === "del" ? st.delete("report") : st.put(value, "report");
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
  } catch { return undefined; }
}

async function queueReport(body) {
  await outbox("put", { body: { ...body, queued_at: new Date().toISOString() }, saved_at: Date.now() });
  try {     // Android Chrome can send it in the background even after the page is closed
    const reg = await navigator.serviceWorker.ready;
    if (reg.sync) await reg.sync.register("send-report");
  } catch { }
  renderOutbox();
}

async function renderOutbox() {
  const item = await outbox("get");
  $("outbox").hidden = !item;
  if (!item) return;
  $("outbox-text").textContent = t("outboxWaiting")(fmt(item.body.queued_at));
  $("outbox-rescue").hidden = !(item.body.needs || []).includes("rescue");
}

let flushing = false;
async function flushOutbox() {
  if (flushing) return;
  const item = await outbox("get");
  if (!item) { renderOutbox(); return; }
  flushing = true;
  try {
    const r = await call("/public/report", item.body);
    await outbox("del");
    R.last = r.report.reported_at;
    $("r-last").textContent = t("lastReport")(fmt(R.last));
    toast(t("outboxSent"));
  } catch (err) {
    if (err.status === 401) { store("v-signed-in", "0"); showReportStep("phone"); reportError(t("outboxSignIn")); }
    else if (err.status >= 400 && err.status < 500) { await outbox("del"); reportError(err.message); }   // refused: don't retry forever
    // no status = still no network: keep it and try again later
  } finally {
    flushing = false;
    renderOutbox();
  }
}

function setOffline(off) {
  $("net-banner").hidden = !off;
  if (!off) flushOutbox();
}

window.addEventListener("online", () => { setOffline(false); refresh(); });
window.addEventListener("offline", () => setOffline(true));
document.addEventListener("visibilitychange", () => { if (!document.hidden) flushOutbox(); });

// ---------- SOS by SMS (works with no mobile data) ----------
function gpsOnce() {
  if (!("geolocation" in navigator) || !window.isSecureContext) return Promise.resolve(null);
  return new Promise((resolve) => navigator.geolocation.getCurrentPosition(
    (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }), () => resolve(null),
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 300000 }));      // GPS works without internet
}

$("btn-sms").addEventListener("click", async () => {
  const v = S.data && S.data.village;
  const place = v ? `${v.name}, ${v.taluk}, ${v.district}` : "";
  const people = CATS.reduce((n, c) => n + R.counts[c], 0);
  const pos = S.loc || await gpsOnce();
  const loc = pos ? `https://maps.google.com/?q=${pos.lat.toFixed(5)},${pos.lon.toFixed(5)}` : "";
  const text = t("smsBody")(place, people, R.counts.unknown, loc);
  openUrl(`sms:?&body=${encodeURIComponent(text)}`);        // opens the SMS app with the message ready
});
function openUrl(u) { window.location.href = u; }

// ---------- install as an app ----------
let installPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; $("btn-install").hidden = false; });
$("btn-install").addEventListener("click", async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  try { await installPrompt.userChoice; } catch { }
  installPrompt = null; $("btn-install").hidden = true;
});
window.addEventListener("appinstalled", () => { $("btn-install").hidden = true; });

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/villager/sw.js").catch(() => { /* http on a phone: no offline mode */ });
  navigator.serviceWorker.addEventListener("message", (e) => {
    if (e.data && e.data.type === "outbox-sent") { toast(t("outboxSent")); renderOutbox(); initReport(); }
    if (e.data && e.data.type === "outbox-refused") renderOutbox();
  });
}

$("r-logout").addEventListener("click", async () => {
  try { await call("/public/auth/logout", {}); } catch { }
  R.counts = { at_shelter: 0, with_relatives: 0, at_home: 0, unknown: 0 }; R.needs = new Set(); R.last = null;
  renderReportForm();
  showReportStep("phone");
});

// ---------- start ----------
async function start() {
  S.lang = load("v-lang") === "en" ? "en" : "kn";
  S.village = load("v-village") || null;
  $("demo-banner").hidden = !DEMO;
  try { S.districts = await (await fetch("/public/districts")).json(); } catch { S.districts = []; }
  applyLang();
  showHome();
  refresh();
  if (S.village) initReport();
  setInterval(refresh, POLL_MS);
  setOffline(!navigator.onLine);
  renderOutbox();
  flushOutbox();
  setInterval(flushOutbox, 30_000);       // keep trying while a saved report waits
}
start();
