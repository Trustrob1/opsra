/**
 * frontend/src/utils/webchatHeader.js
 * Who the web chat header shows: Chioma, or the team. The team takes the header only once a team member has actually replied (or is
 * typing a reply). A chat that was merely handed over (for example after hours, with nobody there yet) keeps Chioma's face and name,
 * because she is still the one answering, and the subtitle says when the team is back.
 */
export function headerState({ human, hasRepReply, repTyping, teamAvailable, online, reopens, businessName }) {
  const withTeam = !!human && (!!hasRepReply || !!repTyping)
  const waiting = !!human && !withTeam
  let subtitle
  if (withTeam) subtitle = null                                   // the page shows the team member's name or "Replying to you here"
  else if (waiting && teamAvailable) subtitle = 'The team is online now and will reply here'
  else if (waiting && reopens) subtitle = `The team is back ${reopens}`
  else subtitle = `Virtual assistant for ${businessName}`
  return { withTeam, subtitle, dotOn: withTeam ? !!teamAvailable : (waiting ? !!online : !!online) }
}
