# su_mcp_bridge.rb — Ruby TCP server para SketchUp (compatible con mcp-sketchup Python)
# Instalación: copiar a Plugins/ o instalar .rbz vía Extension Manager
# Basado en mhyrr/sketchup-mcp y Shattenjagger/sketchup-mcp-bridge (connect-per-command, immortal timer, abort_operation safety)
require 'socket'
require 'json'

module SUMCPBridge
  PORT = 9876
  HOST = '127.0.0.1'
  @server = nil
  @timer = nil
  @running = false

  def self.log(msg)
    puts "[SUMCPBridge] #{msg}"
    Sketchup.active_model ? nil : nil
    begin
      Sketchup.send_action("showRubyPanel:") if defined?(Sketchup)
    rescue
    end
  end

  def self.start_server
    return if @running
    begin
      @server = TCPServer.new(HOST, PORT)
      @server.listen(5)
      @running = true
      log("listening on #{HOST}:#{PORT} — timer loop")
      # UI.start_timer es main-thread safe para SketchUp API
      @timer = UI.start_timer(0.05, true) do
        begin
          # non-blocking accept — evita colgar UI
          ready = IO.select([@server], nil, nil, 0)
          next unless ready
          c = @server.accept_nonblock
          begin
            line = c.gets
            if line
              req = JSON.parse(line.strip) rescue nil
              if req
                id = req['id'] || req['ID'] || 1
                cmd = req['cmd'] || req['type'] || 'eval'
                args = req['args'] || req['params'] || {}
                begin
                  result = handle_command(cmd, args)
                  resp = {"id"=>id, "ok"=>true, "result"=>result}
                  c.write(JSON.dump(resp)+"\n")
                rescue => e
                  begin
                    err = {"id"=>id, "ok"=>false, "error"=>"#{e.class}: #{e.message}\n#{e.backtrace[0..3].join("\n")}"}
                    c.write(JSON.dump(err)+"\n")
                  rescue; end
                end
              end
            end
          rescue => e
            log("handle error: #{e.message}")
          ensure
            c.close rescue nil
          end
        rescue IO::WaitReadable, Errno::EAGAIN
          # no client
        rescue => e
          log("timer error: #{e.message}")
        end
      end
      Sketchup.set_status_text("SUMCPBridge OK :9876") if defined?(Sketchup)
    rescue => e
      @running = false
      puts "SUMCPBridge error: #{e.message}"
      log("start error: #{e.message}")
    end
  end

  def self.stop_server
    @running = false
    UI.stop_timer(@timer) if @timer
    @server.close rescue nil
    @server = nil
    log("stopped")
  end

  def self.handle_command(cmd, args)
    model = Sketchup.active_model
    case cmd.to_s
    when 'get_scene_info', 'getSceneInfo'
      {
        "title"=> model.title,
        "path"=> model.path,
        "entities"=> model.entities.length,
        "active_entities"=> model.active_entities.length,
        "selection"=> model.selection.length,
        "units"=> model.options["UnitsOptions"]["LengthUnit"].to_s,
        "bounds"=> [model.bounds.min, model.bounds.max].map{|p| [p.x, p.y, p.z]},
        "version"=> Sketchup.version
      }
    when 'get_selection', 'get_selected_components', 'getSelection'
      model.selection.map do |e|
        {
          "entityID"=> e.entityID,
          "typename"=> e.typename,
          "bounds"=> (begin; [e.bounds.min, e.bounds.max].map{|p| [p.x, p.y, p.z]}; rescue; nil; end),
          "name"=> e.respond_to?(:name) ? e.name : nil
        }
      end
    when 'eval', 'eval_ruby', 'evalRuby'
      code = args['code'] || args['Code'] || ''
      # wrap en operation con abort safety
      result = nil
      model.start_operation("MCP eval", true)
      begin
        result = eval(code)
        model.commit_operation
      rescue => e
        model.abort_operation
        raise e
      end
      result.to_s
    when 'create_component', 'createComponent'
      # ejemplo básico: crear grupo caja
      name = args['name'] || 'MCP_Box'
      pos = (args['position'] || '0,0,0').split(',').map(&:to_f)
      sz = (args['size'] || '100,100,100').split(',').map(&:to_f)
      model.start_operation("MCP create", true)
      begin
        grp = model.active_entities.add_group
        pts = [
          [pos[0], pos[1], pos[2]],
          [pos[0]+sz[0], pos[1], pos[2]],
          [pos[0]+sz[0], pos[1]+sz[1], pos[2]],
          [pos[0], pos[1]+sz[1], pos[2]]
        ]
        face = grp.entities.add_face(pts)
        face.pushpull(sz[2]) if face
        grp.name = name
        model.commit_operation
        {"entityID"=> grp.entityID, "name"=> name}
      rescue => e
        model.abort_operation
        raise e
      end
    when 'screenshot'
      # requiere view.write_image
      dir = args['screenshot_dir'] || ENV['SKETCHUP_MCP_SCREENSHOT_DIR'] || Dir.tmpdir
      path = File.join(dir, "mcp_shot_#{Time.now.to_i}.png")
      view = Sketchup.active_model.active_view
      view.write_image(path, 0, 0, false, 0, 0)
      {"path"=> path}
    else
      raise "Method not found: #{cmd}"
    end
  end

  unless file_loaded?(__FILE__)
    menu = UI.menu("Extensions")
    menu.add_item("SketchUp MCP Bridge - Start Server") { SUMCPBridge.start_server }
    menu.add_item("SketchUp MCP Bridge - Stop Server") { SUMCPBridge.stop_server }
    file_loaded(__FILE__)
    # Auto-start MCP Bridge
    UI.start_timer(1.5, false) { SUMCPBridge.start_server }
  end
end
