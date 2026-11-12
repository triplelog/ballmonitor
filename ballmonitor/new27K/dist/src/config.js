// Where this copy of the game finds things. The defaults suit the game
// served by its own server (npm run serve). A static build sets them with
//   MP_SERVER=https://27k.example.com INVITE_PAGE=https://ballmonitor.com/27k/ npm run build
// (tools/build-static.js rewrites this file in dist/).

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
