# Community

Projects that other users built on top of this integration. They are maintained by their authors, not by this project.

To add yours, [edit this page](https://github.com/leikoilja/ha-google-home/edit/master/docs/community.md) and open a pull request.

## Dashboard cards

- [Google Home timers card](https://github.com/DurgNomis-drol/google_home_timers_card) by [@DurgNomis-drol](https://github.com/DurgNomis-drol): shows the timers of a device on a dashboard. Its author no longer updates it.

## Node-RED flows

- [Alarms and timers as actionable notifications](https://dev.to/mattieha/get-google-home-alarms-timers-as-notifications-i0m) by [@mattieha](https://github.com/mattieha), from 2021.
- [Broadcast ringing alarms and timers to other devices](https://dev.to/mattieha/broadcast-google-home-alarms-timers-3c13) by [@mattieha](https://github.com/mattieha), from 2021. Its text-to-speech mode calls `tts.google_translate_say`, which Home Assistant adds only for Google Translate text-to-speech set up in YAML. If you added Google Translate in the UI, change that call to the [Speak](https://www.home-assistant.io/actions/tts.speak/) action: target the Google Translate text-to-speech entity, and move the speakers from `entity_id` to `media_player_entity_id`.
