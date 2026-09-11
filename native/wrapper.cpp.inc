
// GhostNet Receiver C ABI adapter, GPL-3.0-or-later.
// Runs the upstream receive algorithm synchronously; no Qt GUI, sound card,
// radio-control, networking, or transmitter code is compiled into this library.
#include "JS8_Mode/DecodedText.h"
#include "JS8_Main/Varicode.h"
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLoggingCategory>
#include <cstring>

Q_LOGGING_CATEGORY(decoder_js8, "decoder.js8", QtWarningMsg)
std::mutex fftw_mutex;
static std::mutex call_mutex;
using ReceiverCallback = void (*)(char const *, void *);

extern "C" __declspec(dllexport)
int ghostnet_validate_message(char const *command, char const *body,
                              ReceiverCallback callback, void *context) {
    if (!command || !body || !callback) return -1;
    auto cmd=QString::fromUtf8(command);
    auto message=Varicode::rstrip(QString::fromUtf8(body));
    auto bits=Varicode::isCommandChecksumed(cmd);
    bool valid=true;
    if (bits) {
        message=Varicode::lstrip(message);
        int size=bits==32 ? 6 : 3;
        auto checksum=message.right(size);
        auto payload=message.left(std::max(0,int(message.length())-size-1));
        valid=message.length()>=size+1 && message[message.length()-size-1]==' ' &&
            (bits==32 ? Varicode::checksum32Valid(checksum,payload) : Varicode::checksum16Valid(checksum,payload));
        if(valid) message=payload;
    }
    auto json=QJsonDocument(QJsonObject{{"text",message},{"valid",valid},{"checksum_bits",bits}}).toJson(QJsonDocument::Compact);
    callback(json.constData(),context);
    return valid ? 1 : 0;
}

extern "C" __declspec(dllexport)
int ghostnet_decode(std::int16_t const *samples, int length, int mode, int utc,
                    ReceiverCallback callback, void *context) {
    try {
        std::lock_guard lock(call_mutex);
        if (!samples || !callback || length < 1 || length > JS8_RX_SAMPLE_SIZE)
            return -1;
        auto data = std::make_unique<struct dec_data>();
        std::memset(data.get(), 0, sizeof(*data));
        std::copy(samples, samples+length, data->d2);
        data->params.nutc = utc;
        data->params.nfa = 0;
        data->params.nfb = 3500;
        data->params.nfqso = 1500;
        data->params.newdat = true;
        auto emitEvent = [&](JS8::Event::Variant const &event) {
            if (auto decoded = std::get_if<JS8::Event::Decoded>(&event)) {
                DecodedText text(*decoded);
                QJsonObject result;
                result["text"] = text.message();
                result["frame"] = text.frame();
                result["bits"] = text.bits();
                result["frame_type"] = text.frameType();
                result["snr"] = text.snr();
                result["offset"] = text.frequencyOffset();
                result["dt"] = text.dt();
                result["mode"] = text.submode();
                result["low_confidence"] = text.isLowConfidence();
                result["compound"] = text.compoundCall();
                result["heartbeat"] = text.isHeartbeat();
                result["directed"] = QJsonArray::fromStringList(text.directedMessage());
                auto json = QJsonDocument(result).toJson(QJsonDocument::Compact);
                callback(json.constData(), context);
            }
        };
        switch (mode) {
        case 0: { if(length>ModeA::NMAX) return -1;
                  static auto d=std::make_unique<DecodeMode<ModeA>>();
                  return (*d)(*data,0,length,emitEvent); }
        case 1: { if(length>ModeB::NMAX) return -1;
                  static auto d=std::make_unique<DecodeMode<ModeB>>();
                  return (*d)(*data,0,length,emitEvent); }
        case 2: { if(length>ModeC::NMAX) return -1;
                  static auto d=std::make_unique<DecodeMode<ModeC>>();
                  return (*d)(*data,0,length,emitEvent); }
        case 4: { if(length>ModeE::NMAX) return -1;
                  static auto d=std::make_unique<DecodeMode<ModeE>>();
                  return (*d)(*data,0,length,emitEvent); }
        case 8: { if(length>ModeI::NMAX) return -1;
                  static auto d=std::make_unique<DecodeMode<ModeI>>();
                  return (*d)(*data,0,length,emitEvent); }
        default: return -1;
        }
    } catch (std::exception const &e) {
        QJsonObject err{{"error",QString::fromUtf8(e.what())}};
        auto json=QJsonDocument(err).toJson(QJsonDocument::Compact);
        callback(json.constData(),context);
        return -2;
    }
}
