--!nonstrict
return function()
    local model = require("./model.luau")
    local checked = 0
    local function check(value, message) assert(value, message) checked = checked + 1 end
    local readState=require("./read_state.luau")
    local unread={id="read-test",lastActivityAt=100,lastText="你好",unread=2,hasUnread=true}
    local receipt={["read-test"]=readState.token(unread)}
    check(readState.apply({unread},receipt)[1].unread==0,"viewed revision clears unread")
    check(unread.unread==2,"read overlay preserves source roster")
    local newer=table.clone(unread) newer.lastActivityAt=101
    check(readState.apply({newer},receipt)[1].unread==2,"new reply restores unread")
    newer=table.clone(unread) newer.unread=3
    check(readState.apply({newer},receipt)[1].unread==3,"identical new text restores unread")
    check(not readState.matchesLatest(unread,{}),"empty transcript is not read")
    check(not readState.matchesLatest(unread,{{text="旧消息"}}),"stale transcript is not read")
    check(readState.matchesLatest(unread,{{text="你好"}}),"latest loaded message matches roster")
    local pins=require("./pins.luau")
    local roster={running=true,agents={{id="idle",name="Idle",state="idle"},{id="busy",name="Busy",state="working"}}}
    local members,extra=pins.members(roster,{idle=true},10)
    check(#members==2 and members[1].id=="idle","idle pinned member precedes automatic workers")
    roster.running=false
    check(#pins.members(roster,{idle=true},10)==1,"pinned member stays when app stops")
    check(#pins.members(roster,{},10)==0,"unpinned idle members remain hidden")
    roster.running=true
    members,extra=pins.members(roster,{idle=true,busy=true},1)
    check(#members==1 and extra==1,"pinned and working members deduplicate and respect limit")
    local defaultShape,defaultColor=require("./avatar_defaults.luau").resolve("56cb67b7-c028-4151-ac86-1f147d465090")
    check(defaultShape=="teardrop" and defaultColor=="green","generated avatar matches application defaults")
    check(model.key("nbswy3dp.blob") == "hello", "base32 file decoding")
    check(model.key("invalid!.blob") == "", "ignore unrelated files")
    local rows, err = model.parse({schemaVersion=4,value={rows={
        {id="a",name="中文代理",awaitingUserResponse={reason="approval_required",reasonCopy=""},unreadCount=2},
        {id="b",name="worker",hasUnread=true},
        {id="c",name="removed",isRemovedFromSidebar=true},
        {id="d",name="hidden",isHiddenFromSidebar=true},
        {id="e",name="idle"},
    }}})
    check(err=="" and #rows==3, "schema 4 and sidebar filters")
    check(rows[1].reason=="需要你批准", "empty reasonCopy fallback")
    check(rows[1].name=="中文代理", "UTF-8 names")
    local agents, counts, mood=model.decorate(rows,{b=99500},100000,12000,true)
    check(mood=="waiting" and agents[1].id=="a", "waiting takes priority")
    check(counts.working==1 and counts.waiting==1 and counts.total==3, "working and counts")
    local _, expired = model.decorate(rows,{b=80000},100000,12000,true)
    check(expired.working==0 and expired.unread==1, "working timeout preserves unread")
    local _, _, stopped = model.decorate(rows,{},100000,12000,false)
    check(stopped=="asleep", "stopped app sleeps")
    check(model.clean("甲乙丙丁",2)=="甲乙…", "UTF-8 truncation")
    check(model.clean("x\ny\000z",20)=="x y z", "strip control characters")
    local invalid = model.parse({schemaVersion=99,value={}})
    check(invalid==nil,"unsupported structure is visible as an error")
    check(model.pendingTask({lastText="已经开始查了,有结果马上发你。",lastActivityAt=1000},20000),"background work survives quiet output")
    check(not model.pendingTask({lastText="已经完成，结果如下",lastActivityAt=1000},20000),"final result clears background inference")
    check(not model.pendingTask({lastText="正在查询",lastActivityAt=1000},2000000),"background inference expires")
    local clockModule=require("./animation_clock.luau")
    local clock={phase=731,last=1000,paused=true}
    check(clockModule.step(clock,1300,true)==731,"opening holds frozen pose")
    check(clockModule.step(clock,1360,false)==731,"resume starts on exact frozen frame")
    check(clockModule.step(clock,1393,false)==764,"normal playback advances smoothly")
    check(clockModule.step(clock,1426,true)==764,"closing keeps current expression")
    check(clockModule.step(clock,50000,true)==764,"closed time never advances expression")
    check(clockModule.step(clock,50360,false)==764,"reopen preserves pose continuity")
    local first={phase=100,last=1000,paused=true}
    local second={phase=200,last=1000,paused=true}
    clockModule.step(first,1033,false)
    clockModule.step(second,1033,true)
    check(clockModule.step(first,1066,false)==133 and clockModule.step(second,1066,true)==200,"revealed member animates while next stays hidden")
    check(clockModule.step(second,1099,false)==200,"next member starts without a pose jump")
    check(clockModule.step(second,1132,false)==233,"next member advances independently")
    local chatModule=require("./chat.luau")
    local accepted,why=chatModule.handoff("test","")
    check(not accepted and why=="请输入消息","empty message never launches app")
    accepted,why=chatModule.handoff("test",string.rep("x",1001))
    check(not accepted,"oversize draft rejected without sending")
    local transition=require("./chat_transition.luau")
    check(transition.toggle("a","a")==nil,"same avatar closes chat")
    check(transition.toggle(nil,"a")=="a","avatar opens chat")
    check(transition.toggle("a","b")=="b","other avatar switches chat")
    check(transition.progress(130,.0,1,0)==.5,"chat reveal interpolates")
    check(transition.progress(260,1,0,0)==0,"chat collapse ends at zero")
    local _,_,runtimeMood=model.decorate({{id="runtime",name="Test",runtimeKnown=true,runtimeRunning=true,waiting=false,hasUnread=false,unread=0,lastActivityAt=0}}, {},100000,12000,true)
    check(runtimeMood=="working","live runtime keeps a silent task working")
    local _,_,finishedMood=model.decorate({{id="runtime",name="Test",runtimeKnown=true,runtimeRunning=false,waiting=false,hasUnread=false,unread=0,lastActivityAt=99000,lastText="正在查询"}}, {runtime=99000},100000,12000,true)
    check(finishedMood=="idle","live completion overrides stale text and file activity")
    local layout=require("./layout.luau")
    check(layout.barLimit==10 and layout.pageLimit==32,"new display limits")
    local nine=layout.rowSizes(9)
    check(#nine==2 and nine[1]==8 and nine[2]==1,"nine members form full row and centered single row")
    local full=layout.rowSizes(32)
    check(#full==4 and full[4]==8,"32 members fit four rows")
    local partial=layout.rowSizes(25)
    check(#partial==4 and partial[4]==1,"last single member has its own centered row")
    local peek = require("./peek.luau")
    local face = require("./face.luau")
    for _,shape in ipairs({"house","square","wedge"}) do
        local shapePath=face.path("idle",0,shape,"orange")
        check(string.find(shapePath,"-"..shape.."-",1,true)~=nil,"picker shape does not fall back: "..shape)
        check(noctalia.fileExists(shapePath),"picker shape generates SVG: "..shape)
    end
    local image = face.path("working",0)
    local sample = {running=true, agents={}}
    for i=1,4 do table.insert(sample.agents,{id="peek-test-"..tostring(i),name="Test",state="working",waiting=false,avatarShape="heart",avatarColor="blue"}) end
    local path,width,overflow,count = peek.render(sample,1000,image)
    check(count==4 and overflow==0,"four working members are visible")
    path,width,overflow,count=peek.render(sample,1060,image)
    check(width>26 and noctalia.fileExists(path),"working members generate composite SVG")
    local svg=noctalia.readFile(path)
    check(string.find(svg,'eyeslead',1,true)~=nil,"composite leader mask is isolated")
    sample.agents[1].state="waiting" sample.agents[1].waiting=true
    path,width,overflow,count=peek.render(sample,1120,image)
    check(count==4,"waiting member remains visible")
    sample.running=false
    for t=1180,1360,60 do path,width,overflow,count=peek.render(sample,t,image) end
    check(count==0 and width==26,"members retract when stopped")
    return {ok=true,checks=checked,updated=noctalia.nowMs()}
end
