// Where this copy of the game finds things. The defaults here suit the game
// served by its own server (npm run serve). The static build (npm run build,
// npm run itch) writes the live values into dist/src/config.js:
// https://27k.ballmonitor.com and https://ballmonitor.com/27k/ unless
// MP_SERVER / INVITE_PAGE say otherwise (tools/build-static.js).

export const CONFIG = {
    // The multiplayer server, e.g. 'https://27k.example.com'. Empty: the
    // address this page came from. With no server answering there,
    // Multiplayer stays off the menu.
    mpServer: '',
    // The page invite links open, e.g. 'https://ballmonitor.com/27k/'.
    // Empty: this page. Set it when the game runs inside another site's
    // frame (itch.io), whose own address nobody can open.
    invitePage: '',
};
