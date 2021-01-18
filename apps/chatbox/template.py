jsString = """
const css =
    ".autovista-chatbot-chatbox{{z-index:2147483000;position:fixed;bottom:100px;right:20px;width:354px;min-height:250px;max-height:704px;box-shadow:rgba(0,0,0,.16) 0 5px 40px;border-radius:8px;overflow:hidden;opacity:0;height:calc(100% - 150px);transition:all .3s;transform:translateY(20px);pointer-events:none}}.autovista-chatbot-chat{{position:fixed;display:flex;justify-content:center;align-items:center;z-index:2147483000;bottom:20px;right:20px;width:60px;height:60px;background:inherit;border-radius:50%;box-shadow:rgba(0,0,0,.06) 0 1px 6px 0,rgba(0,0,0,.16) 0 2px 32px 0;overflow:hidden}}.autovista-chatbot-label{{position:fixed;bottom:40px;right:104px;background-color:inherit;pointer-events:none;color:#fff;border-radius:10px 0 0 10px}}.autovista-chatbot-left .autovista-chatbot-label{{bottom:40px;right:auto;left:104px;border-radius:0 10px 10px 0}}.autovista-chatbot-label>p{{margin:0;font-size:12px;padding:2px 1px 2px 10px}}.autovista-chatbot-left .autovista-chatbot-label>p{{padding:2px 10px 2px 1px}}.autovista-chatbot-polygon{{position:absolute;left:100%;height:100%;width:20px;clip-path:polygon(0 0,0 100%,100% 50%);background-color:inherit}}.autovista-chatbot-left .autovista-chatbot-polygon{{right:100%;left:auto;clip-path:polygon(0 50%,100% 100%,100% 0)}}.autovista-chatbot-background{{background:inherit;position:absolute;height:100%;width:100%}}.autovista-chatbot-chat-bubble{{cursor:pointer;position:relative}}.autovista-chatbot-bubble{{transform-origin:50%;transition:transform .5s cubic-bezier(.17,.61,.54,.9)}}.autovista-chatbot-line{{fill:none;stroke:#fff;stroke-width:4;stroke-linecap:round;transition:stroke-dashoffset .5s cubic-bezier(.4,0,.2,1)}}.autovista-chatbot-line1{{stroke-dasharray:60 90;stroke-dashoffset:-20}}.autovista-chatbot-line2{{stroke-dasharray:67 87;stroke-dashoffset:-18}}.autovista-chatbot-circle{{fill:#fff;stroke:none;transform-origin:50%;transition:transform .5s cubic-bezier(.4,0,.2,1)}}.autovista-chatbot-active .autovista-chatbot-bubble{{transform:translateX(24px) translateY(4px) rotate(45deg)}}.autovista-chatbot-active .autovista-chatbot-line1{{stroke-dashoffset:21}}.autovista-chatbot-active .autovista-chatbot-line2{{stroke-dashoffset:30}}.autovista-chatbot-active .autovista-chatbot-circle{{transform:scale(0)}}",
  head = document.head || document.getElementsByTagName("head")[0],
  style = document.createElement("style");

head.appendChild(style);
if (style.styleSheet) {{
  // This is required for IE8 and below.
  style.styleSheet.cssText = css;
}} else {{
  style.appendChild(document.createTextNode(css));
}}

const domain = `{}`;
const botId = `{}`;
const origin = window.location.origin;

const elChatBox = document.createElement("div");
const elChatBtn = document.createElement("div");
const elChatBtnLabel = document.createElement("div");
const elIframe = document.createElement("iframe");

elChatBox.classList.add("autovista-chatbot-chatbox");
document.body.appendChild(elChatBox);
elIframe.style.position = 'absolute'
elChatBox.appendChild(elIframe);

elIframe.setAttribute("frameborder", "0");
elIframe.setAttribute("allowfullscreen", "true");
elIframe.setAttribute("height", "100%");
elIframe.setAttribute("width", "100%");
elIframe.setAttribute(
  "src",
  `https://${{domain}}/clientwidget?origin=${{origin}}&h=${{botId}}`
);

const btnContent = `
  <div id="autovista-chat-btn" class="autovista-chatbot-chat">
    <div class="autovista-chatbot-background"></div>
    <svg class="autovista-chatbot-chat-bubble" width="60" height="60" viewBox="0 0 100 100">
      <g class="autovista-chatbot-bubble">
        <path class="autovista-chatbot-line autovista-chatbot-line1" d="M 30.7873,85.113394 30.7873,46.556405 C 30.7873,41.101961 36.826342,35.342 40.898074,35.342 H 59.113981 C 63.73287,35.342 69.29995,40.103201 69.29995,46.784744" />
        <path class="autovista-chatbot-line autovista-chatbot-line2" d="M 13.461999,65.039335 H 58.028684 C 63.483128,65.039335 69.243089,59.000293 69.243089,54.928561 V 45.605853 C 69.243089,40.986964 65.02087,35.419884 58.339327,35.419884" />
      </g>
      <circle class="autovista-chatbot-circle autovista-chatbot-circle1" r="1.9" cy="50.7" cx="42.5" />
      <circle class="autovista-chatbot-circle autovista-chatbot-circle2" cx="49.9" cy="50.7" r="1.9" />
      <circle class="autovista-chatbot-circle autovista-chatbot-circle3" r="1.9" cy="50.7" cx="57.3" />
    </svg>
  </div>`;

elChatBtn.style.opacity = 0;
elChatBtn.style.transition = "all 0.3s";
elChatBtn.style.pointerEvents = "none";
elChatBtn.innerHTML += btnContent;

document.body.appendChild(elChatBtn);

const showChatBox = (isVisible) => {{
  elIframe.contentWindow.postMessage(
    {{ type: "TOGGLE_CHATBOX_VISIBILITY", visible: isVisible }},
    "*"
  );
}};

let chatboxVisible = false;
const toggleChatBox = () => {{
  showChatBox(!chatboxVisible);
  elChatBtn.classList.toggle("autovista-chatbot-active");
  elChatBox.style.opacity = chatboxVisible ? "0" : "1";
  elChatBox.style.pointerEvents = chatboxVisible ? "none" : "all";
  elChatBox.style.transform = chatboxVisible
    ? "translateY(20px)"
    : "translateY(0)";
  chatboxVisible = !chatboxVisible;
}};
elChatBtn.addEventListener("click", toggleChatBox);

function receiveMessage(event) {{
  if (event.origin !== `https://${{domain}}`) {{
    return;
  }}
  if (event.data.type === "LOCALSTORE_IFRAM") {{
    switch (event.data.action) {{
      case "remove": {{
        localStorage.removeItem(event.data.key);
        break;
      }}
      case "get": {{
        let data = localStorage.getItem(event.data.key);
        if (data) data = JSON.parse(data);
        elIframe.contentWindow.postMessage(
          {{ [event.data.key]: data, type: "GET_LOCALDATA" }},
          "*"
        );
        break;
      }}
      case "getUtm": {{
        elIframe.contentWindow.postMessage(
          {{
            utmData: window.location.search.substring(1),
            parent_url: window.location.origin,
            type: "GET_UTM",
          }},
          "*"
        );
        break;
      }}
      case "set": {{
        localStorage.setItem(event.data.key, event.data.val);
        break;
      }}
      default:
        return;
    }}
  }}
}}
window.addEventListener("message", receiveMessage, false);

const onLoad = async () => {{
  const url = `https://${{domain}}/api/chatbox/${{botId}}/chatboxappeareance?website_url=${{window.location.host}}`;
  const res = await fetch(url);
  if (res.status >= 400) return;
  const resData = await res.json();
  const botInfo = JSON.parse(resData.json_info);
  const colors = JSON.parse(botInfo.custom_theme).background.match(
    /#[0-9a-f]{{3,6}}/gi
  );
  const botConfig = {{
    colorPrimary: colors[0],
    colorSecondary: colors[1],
    chatboxname: botInfo.chatboxname,
    widgetPosition: botInfo.widget_position,
    isBotOnline: botInfo.current_status,
    offlineMsg: botInfo.offline_msg,
    onlineStatus: botInfo.online_status,
    offlineStatus: botInfo.offline_status,
    showLabel: botInfo.button_label,
    labelText: botInfo.label_text,
  }};
  elIframe.contentWindow.postMessage(
    {{
      type: "BOT_INFO",
      config: botConfig,
    }},
    "*"
  );
  if (botConfig.widgetPosition === "L") {{
    const btn = document.getElementById("autovista-chat-btn");
    btn.style.left = "20px";
    btn.style.right = "auto";
    elChatBox.style.left = "20px";
    elChatBox.style.right = "auto";
  }}
  if (botInfo.button_label) {{
    const btnLabelContent = `
      <div class="autovista-chatbot-label">
        <div class="autovista-chatbot-polygon"></div>
        <p>${{botInfo.label_text}}</p>
      </div>
    `;
    elChatBtnLabel.innerHTML += btnLabelContent;
    if (botConfig.widgetPosition === "L") {{
      elChatBtnLabel.classList.toggle("autovista-chatbot-left");
    }}
    elChatBtnLabel.style.backgroundColor = botConfig.colorSecondary;

    elChatBtn.appendChild(elChatBtnLabel);
  }}
  if (botInfo.defaultOpen) {{
    toggleChatBox();
  }}
  elChatBtn.style.background = colors[1];
  elChatBtn.style.opacity = 1;
  elChatBtn.style.pointerEvents = "all";
}};

window.onload = onLoad;

"""
